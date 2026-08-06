"""SPARQL validation of a PROV-O workflow knowledge graph on a triple store.

All rules (R1–R6) are executed as SPARQL SELECT queries against a remote SPARQL 1.1
endpoint after the Turtle KG is bulk-loaded via the Graph Store Protocol.

Requires endpoint env vars (see ``src.sparql_endpoint`` / README). Start a local
Fuseki with: ``docker compose -f docker-compose.fuseki.yml up -d``.

The previous in-memory Python traversal engine is archived under
``archive/python_rdflib_validation/``.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline_config import load_pipeline_config
from src.sparql_endpoint import SparqlEndpoint, SparqlEndpointError
from src.validation_rules import VALIDATION_RULES, ValidationRule


@dataclass(frozen=True)
class RuleViolation:
    issue: str
    details: dict[str, str]


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    name: str
    description: str
    status: str
    violation_count: int
    duration_seconds: float
    violations: tuple[RuleViolation, ...]


@dataclass(frozen=True)
class ValidationReport:
    status: str
    knowledge_graph: str
    report_path: str
    started_at: str
    finished_at: str
    duration_seconds: float
    total_violations: int
    rules_run: tuple[str, ...]
    results: tuple[RuleResult, ...]
    load_seconds: float | None = None
    query_endpoint: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"


def _violations_from_sparql_rows(rows: list[dict[str, str]]) -> list[RuleViolation]:
    violations: list[RuleViolation] = []
    for row in rows:
        details = dict(row)
        issue = details.pop("issue", "violation")
        violations.append(RuleViolation(issue=issue, details=details))
    return violations


def _run_rule(endpoint: SparqlEndpoint, rule: ValidationRule) -> RuleResult:
    started = time.perf_counter()
    rows = endpoint.select(rule.query)
    violations = _violations_from_sparql_rows(rows)
    duration = round(time.perf_counter() - started, 6)
    return RuleResult(
        rule_id=rule.rule_id,
        name=rule.name,
        description=rule.description,
        status="PASSED" if not violations else "FAILED",
        violation_count=len(violations),
        duration_seconds=duration,
        violations=tuple(violations),
    )


def validate_knowledge_graph(
    *,
    knowledge_graph_path: Path,
    report_path: Path,
    rules: tuple[ValidationRule, ...] = VALIDATION_RULES,
    sparql_endpoint: SparqlEndpoint | None = None,
    load_seconds: float | None = None,
) -> ValidationReport:
    """Run SPARQL rules against an already-loaded triple store."""
    endpoint = sparql_endpoint or SparqlEndpoint()
    started_at = datetime.now(timezone.utc).isoformat()
    wall_started = time.perf_counter()
    results = tuple(_run_rule(endpoint, rule) for rule in rules)
    duration = round(time.perf_counter() - wall_started, 6)
    finished_at = datetime.now(timezone.utc).isoformat()
    total_violations = sum(result.violation_count for result in results)
    status = "PASSED" if all(result.status == "PASSED" for result in results) else "FAILED"

    report = ValidationReport(
        status=status,
        knowledge_graph=str(knowledge_graph_path),
        report_path=str(report_path),
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration,
        total_violations=total_violations,
        rules_run=tuple(rule.rule_id for rule in rules),
        results=results,
        load_seconds=load_seconds,
        query_endpoint=endpoint.config.query_endpoint,
    )
    _write_report(report, report_path)
    return report


def validate_ttl(
    knowledge_graph_path: Path,
    *,
    report_path: Path,
    rules: tuple[ValidationRule, ...] = VALIDATION_RULES,
    sparql_endpoint: SparqlEndpoint | None = None,
) -> tuple[ValidationReport, float]:
    """Load Turtle into the store, then run SPARQL validation.

    Returns ``(report, load_seconds)`` where load is CLEAR + Graph Store upload.
    """
    ttl = Path(knowledge_graph_path)
    if not ttl.is_file():
        raise FileNotFoundError(ttl)

    endpoint = sparql_endpoint or SparqlEndpoint()
    load_started = time.perf_counter()
    endpoint.load_turtle(ttl)  # CLEAR + upload
    load_seconds = round(time.perf_counter() - load_started, 6)

    report = validate_knowledge_graph(
        knowledge_graph_path=ttl,
        report_path=report_path,
        rules=rules,
        sparql_endpoint=endpoint,
        load_seconds=load_seconds,
    )
    return report, load_seconds


def _write_report(report: ValidationReport, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": report.status,
        "knowledge_graph": report.knowledge_graph,
        "report_path": report.report_path,
        "engine": "sparql",
        "query_endpoint": report.query_endpoint,
        "load_seconds": report.load_seconds,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "duration_seconds": report.duration_seconds,
        "total_violations": report.total_violations,
        "rules_run": list(report.rules_run),
        "results": [
            {
                "rule_id": result.rule_id,
                "name": result.name,
                "description": result.description,
                "status": result.status,
                "violation_count": result.violation_count,
                "duration_seconds": result.duration_seconds,
                "violations": [asdict(violation) for violation in result.violations],
            }
            for result in report.results
        ],
    }
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def log_validation_summary(report: ValidationReport) -> None:
    print(f"Validation {report.status} (SPARQL triple store).")
    print(f"Knowledge graph: {report.knowledge_graph}")
    if report.query_endpoint:
        print(f"Query endpoint: {report.query_endpoint}")
    print(f"Report written to: {report.report_path}")
    if report.load_seconds is not None:
        print(f"Load duration (CLEAR+upload): {report.load_seconds:.4f}s")
    print(f"Rules run: {', '.join(report.rules_run)}")
    print(f"Total violations: {report.total_violations}")
    print(f"Validation duration: {report.duration_seconds:.4f}s")
    for result in report.results:
        print(
            f"- {result.rule_id} ({result.name}): {result.status} "
            f"[{result.violation_count} violation(s), {result.duration_seconds:.4f}s]"
        )
        if result.status == "PASSED":
            print(f"  {result.rule_id} passed successfully.")
            continue
        for violation in result.violations[:20]:
            detail = ", ".join(
                f"{key}={value}" for key, value in sorted(violation.details.items())
            )
            suffix = f" ({detail})" if detail else ""
            print(f"  - {violation.issue}{suffix}")
        if result.violation_count > 20:
            print(f"  ... and {result.violation_count - 20} more")


def run_from_config(config_path: Path | None = None) -> ValidationReport:
    from src.pipeline_config import DEFAULT_CONFIG_PATH

    config = load_pipeline_config(config_path or DEFAULT_CONFIG_PATH)
    if not config.knowledge_graph_path.is_file():
        raise FileNotFoundError(
            f"Knowledge graph not found: {config.knowledge_graph_path}. "
            "Run conversion first or set knowledge_graph to an existing .ttl file."
        )

    rules = config.selected_validation_rules()
    if not rules:
        raise ValueError(
            "No validation rules enabled. Set e.g. R1 = true under [validation]."
        )
    report, _load = validate_ttl(
        config.knowledge_graph_path,
        report_path=config.validation_report_path,
        rules=rules,
    )
    log_validation_summary(report)
    return report


def main() -> None:
    try:
        run_from_config()
    except SparqlEndpointError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
