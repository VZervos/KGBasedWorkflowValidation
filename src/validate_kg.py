"""Independent SPARQL validation of a generated PROV-O knowledge graph.

Can be run alone (python -m src.validate_kg) or as a pipeline stage.
Does not depend on XES conversion; it only reads the KG path from config.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Graph, Literal
from rdflib.namespace import PROV, RDF, RDFS
from rdflib.query import ResultRow

from src.pipeline_config import load_pipeline_config
from src.validation_rules import VALIDATION_RULES, ValidationRule
from src.xes_to_prov_kg import WF, load_graph


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

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"


def _row_bindings(row: ResultRow) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for name in row.labels:
        value = row[name]
        if value is not None:
            bindings[str(name)] = str(value)
    return bindings


def _ancestors(graph: Graph, start) -> set:
    seen: set = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for earlier in graph.objects(node, PROV.wasInformedBy):
            stack.append(earlier)
    return seen


def _has_valid_payment_chain(graph: Graph, payment) -> bool:
    """Same semantics as R6 SPARQL, but O(edges) BFS instead of SPARQL property paths."""
    cases = list(graph.objects(payment, WF.belongsToCase))
    if len(cases) != 1:
        return False
    case = cases[0]
    request_label = Literal("Request Payment")
    approval_label = Literal("Declaration FINAL_APPROVED by SUPERVISOR")
    submission_label = Literal("Declaration SUBMITTED by EMPLOYEE")

    for request in _ancestors(graph, payment):
        if request_label not in set(graph.objects(request, RDFS.label)):
            continue
        if case not in set(graph.objects(request, WF.belongsToCase)):
            continue
        for approval in _ancestors(graph, request):
            if approval_label not in set(graph.objects(approval, RDFS.label)):
                continue
            if case not in set(graph.objects(approval, WF.belongsToCase)):
                continue
            for submission in _ancestors(graph, approval):
                if submission_label not in set(graph.objects(submission, RDFS.label)):
                    continue
                if case in set(graph.objects(submission, WF.belongsToCase)):
                    return True
    return False


def _run_r6_python(graph: Graph) -> list[RuleViolation]:
    payment_label = Literal("Payment Handled")
    violations: list[RuleViolation] = []
    for payment in graph.subjects(RDF.type, PROV.Activity):
        if payment_label not in set(graph.objects(payment, RDFS.label)):
            continue
        cases = list(graph.objects(payment, WF.belongsToCase))
        if not cases:
            violations.append(
                RuleViolation(
                    issue="invalid_payment_provenance_chain",
                    details={"payment": str(payment), "case": "(missing)"},
                )
            )
            continue
        # One violation per payment if no valid chain for its primary case.
        case = cases[0]
        if not _has_valid_payment_chain(graph, payment):
            violations.append(
                RuleViolation(
                    issue="invalid_payment_provenance_chain",
                    details={"payment": str(payment), "case": str(case)},
                )
            )
    return violations


def _run_rule(graph: Graph, rule: ValidationRule) -> RuleResult:
    started = time.perf_counter()
    # rdflib property paths are too slow on large graphs for R6.
    if rule.rule_id == "R6":
        violations = _run_r6_python(graph)
    else:
        violations = []
        for row in graph.query(rule.query):
            details = _row_bindings(row)
            issue = details.pop("issue", "violation")
            violations.append(RuleViolation(issue=issue, details=details))
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
    graph: Graph,
    *,
    knowledge_graph_path: Path,
    report_path: Path,
    rules: tuple[ValidationRule, ...] = VALIDATION_RULES,
) -> ValidationReport:
    started_at = datetime.now(timezone.utc).isoformat()
    wall_started = time.perf_counter()
    results = tuple(_run_rule(graph, rule) for rule in rules)
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
    )
    _write_report(report, report_path)
    return report


def _write_report(report: ValidationReport, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": report.status,
        "knowledge_graph": report.knowledge_graph,
        "report_path": report.report_path,
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
    print(f"Validation {report.status}.")
    print(f"Knowledge graph: {report.knowledge_graph}")
    print(f"Report written to: {report.report_path}")
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

    graph = load_graph(config.knowledge_graph_path)
    rules = config.selected_validation_rules()
    if not rules:
        raise ValueError(
            "No validation rules enabled. Set e.g. R1 = true under [validation]."
        )
    report = validate_knowledge_graph(
        graph,
        knowledge_graph_path=config.knowledge_graph_path,
        report_path=config.validation_report_path,
        rules=rules,
    )
    log_validation_summary(report)
    return report


def main() -> None:
    run_from_config()


if __name__ == "__main__":
    main()
