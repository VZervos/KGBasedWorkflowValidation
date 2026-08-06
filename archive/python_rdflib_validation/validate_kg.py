"""Independent validation of a generated PROV-O knowledge graph.

Engines:
  python (default) — R1–R4/R6 via in-memory traversals; R5/R5B via rdflib SPARQL.
  sparql           — all rules as SPARQL SELECT against a remote triple store
                     (Fuseki / GraphDB / Blazegraph / …).

Select with KG_VALIDATION_ENGINE=python|sparql or the ``engine`` argument.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal as EngineName

from rdflib import Graph, Literal
from rdflib.namespace import PROV, RDF, RDFS
from rdflib.query import ResultRow

from src.pipeline_config import load_pipeline_config
from src.sparql_endpoint import SparqlEndpoint, SparqlEndpointError
from src.validation_rules import VALIDATION_RULES, ValidationRule
from src.xes_to_prov_kg import WF, load_graph

ValidationEngine = EngineName["python", "sparql"]


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
    engine: str = "python"
    load_seconds: float | None = None

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"


def resolve_validation_engine(explicit: str | None = None) -> ValidationEngine:
    raw = (explicit or os.environ.get("KG_VALIDATION_ENGINE") or "python").strip().lower()
    if raw in {"python", "local", "rdflib"}:
        return "python"
    if raw in {"sparql", "triplestore", "endpoint"}:
        return "sparql"
    raise ValueError(
        f"Unknown validation engine {raw!r}. Use 'python' or 'sparql'."
    )


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


def _activities_by_label(graph: Graph, label: Literal) -> list:
    return [
        activity
        for activity in graph.subjects(RDF.type, PROV.Activity)
        if label in set(graph.objects(activity, RDFS.label))
    ]


def _run_r1_python(graph: Graph) -> list[RuleViolation]:
    """DECLARE existence: every case must contain a submission activity."""
    submission = Literal("Declaration SUBMITTED by EMPLOYEE")
    cases = {case for _act, _p, case in graph.triples((None, WF.belongsToCase, None))}
    cases_with_submission = {
        case
        for act in _activities_by_label(graph, submission)
        for case in graph.objects(act, WF.belongsToCase)
    }
    return [
        RuleViolation(
            issue="missing_submission_existence",
            details={"case": str(case)},
        )
        for case in sorted(cases - cases_with_submission, key=str)
    ]


def _run_r2_python(graph: Graph) -> list[RuleViolation]:
    """DECLARE response: Request Payment must follow FINAL_APPROVED via wasInformedBy+."""
    approval_label = Literal("Declaration FINAL_APPROVED by SUPERVISOR")
    request_label = Literal("Request Payment")
    approvals = _activities_by_label(graph, approval_label)
    covered: set = set()
    for request in _activities_by_label(graph, request_label):
        cases = list(graph.objects(request, WF.belongsToCase))
        if not cases:
            continue
        case = cases[0]
        for anc in _ancestors(graph, request):
            if approval_label in set(graph.objects(anc, RDFS.label)):
                if case in set(graph.objects(anc, WF.belongsToCase)):
                    covered.add(anc)
    violations: list[RuleViolation] = []
    for approval in approvals:
        if approval in covered:
            continue
        cases = list(graph.objects(approval, WF.belongsToCase))
        if not cases:
            continue
        violations.append(
            RuleViolation(
                issue="missing_response_request_after_approval",
                details={"case": str(cases[0]), "approval": str(approval)},
            )
        )
    return violations


def _run_r3_python(graph: Graph) -> list[RuleViolation]:
    """DECLARE precedence: Payment Handled must have Request Payment ancestor."""
    payment_label = Literal("Payment Handled")
    request_label = Literal("Request Payment")
    violations: list[RuleViolation] = []
    for payment in _activities_by_label(graph, payment_label):
        cases = list(graph.objects(payment, WF.belongsToCase))
        if not cases:
            continue
        case = cases[0]
        ok = any(
            request_label in set(graph.objects(anc, RDFS.label))
            and case in set(graph.objects(anc, WF.belongsToCase))
            for anc in _ancestors(graph, payment)
        )
        if not ok:
            violations.append(
                RuleViolation(
                    issue="missing_precedence_request_before_payment",
                    details={"case": str(case), "payment": str(payment)},
                )
            )
    return violations


def _run_r4_python(graph: Graph) -> list[RuleViolation]:
    """DECLARE succession: request→payment and payment←request."""
    payment_label = Literal("Payment Handled")
    request_label = Literal("Request Payment")
    requests = _activities_by_label(graph, request_label)
    payments = _activities_by_label(graph, payment_label)
    violations: list[RuleViolation] = []

    covered_requests: set = set()
    for payment in payments:
        cases = list(graph.objects(payment, WF.belongsToCase))
        if not cases:
            continue
        case = cases[0]
        ancs = _ancestors(graph, payment)
        has_request = False
        for anc in ancs:
            if request_label in set(graph.objects(anc, RDFS.label)):
                if case in set(graph.objects(anc, WF.belongsToCase)):
                    covered_requests.add(anc)
                    has_request = True
        if not has_request:
            violations.append(
                RuleViolation(
                    issue="missing_succession_precedence_request_before_payment",
                    details={"case": str(case), "activity": str(payment)},
                )
            )

    for request in requests:
        if request in covered_requests:
            continue
        cases = list(graph.objects(request, WF.belongsToCase))
        if not cases:
            continue
        violations.append(
            RuleViolation(
                issue="missing_succession_response_payment_after_request",
                details={"case": str(cases[0]), "activity": str(request)},
            )
        )
    return violations


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
        case = cases[0]
        if not _has_valid_payment_chain(graph, payment):
            violations.append(
                RuleViolation(
                    issue="invalid_payment_provenance_chain",
                    details={"payment": str(payment), "case": str(case)},
                )
            )
    return violations


def _violations_from_sparql_rows(rows: list[dict[str, str]]) -> list[RuleViolation]:
    violations: list[RuleViolation] = []
    for row in rows:
        details = dict(row)
        issue = details.pop("issue", "violation")
        violations.append(RuleViolation(issue=issue, details=details))
    return violations


def _run_rule_python(graph: Graph, rule: ValidationRule) -> RuleResult:
    started = time.perf_counter()
    # rdflib SPARQL (esp. property paths / NOT EXISTS) is too slow on full BPI graphs.
    if rule.rule_id == "R1":
        violations = _run_r1_python(graph)
    elif rule.rule_id == "R2":
        violations = _run_r2_python(graph)
    elif rule.rule_id == "R3":
        violations = _run_r3_python(graph)
    elif rule.rule_id == "R4":
        violations = _run_r4_python(graph)
    elif rule.rule_id == "R6":
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


def _run_rule_sparql(endpoint: SparqlEndpoint, rule: ValidationRule) -> RuleResult:
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


def _run_rule(graph: Graph, rule: ValidationRule) -> RuleResult:
    return _run_rule_python(graph, rule)


def validate_knowledge_graph(
    graph: Graph | None,
    *,
    knowledge_graph_path: Path,
    report_path: Path,
    rules: tuple[ValidationRule, ...] = VALIDATION_RULES,
    engine: str | None = None,
    sparql_endpoint: SparqlEndpoint | None = None,
    load_seconds: float | None = None,
) -> ValidationReport:
    """Validate an already-prepared graph (python) or store (sparql).

    Prefer :func:`validate_ttl` for experiment scripts; it handles loading.
    """
    resolved = resolve_validation_engine(engine)
    started_at = datetime.now(timezone.utc).isoformat()
    wall_started = time.perf_counter()

    if resolved == "sparql":
        endpoint = sparql_endpoint or SparqlEndpoint()
        results = tuple(_run_rule_sparql(endpoint, rule) for rule in rules)
    else:
        if graph is None:
            raise ValueError("python engine requires an rdflib Graph")
        results = tuple(_run_rule_python(graph, rule) for rule in rules)

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
        engine=resolved,
        load_seconds=load_seconds,
    )
    _write_report(report, report_path)
    return report


def validate_ttl(
    knowledge_graph_path: Path,
    *,
    report_path: Path,
    rules: tuple[ValidationRule, ...] = VALIDATION_RULES,
    engine: str | None = None,
    sparql_endpoint: SparqlEndpoint | None = None,
) -> tuple[ValidationReport, float]:
    """Load a Turtle KG and validate it.

    Returns ``(report, load_seconds)``. For ``sparql``, load = CLEAR + GSP upload
    into the triple store. For ``python``, load = rdflib Turtle parse.
    """
    resolved = resolve_validation_engine(engine)
    ttl = Path(knowledge_graph_path)
    if not ttl.is_file():
        raise FileNotFoundError(ttl)

    if resolved == "sparql":
        endpoint = sparql_endpoint or SparqlEndpoint()
        load_started = time.perf_counter()
        endpoint.clear()
        endpoint.load_turtle(ttl)
        load_seconds = round(time.perf_counter() - load_started, 6)
        report = validate_knowledge_graph(
            None,
            knowledge_graph_path=ttl,
            report_path=report_path,
            rules=rules,
            engine="sparql",
            sparql_endpoint=endpoint,
            load_seconds=load_seconds,
        )
        return report, load_seconds

    load_started = time.perf_counter()
    graph = load_graph(ttl)
    load_seconds = round(time.perf_counter() - load_started, 6)
    report = validate_knowledge_graph(
        graph,
        knowledge_graph_path=ttl,
        report_path=report_path,
        rules=rules,
        engine="python",
        load_seconds=load_seconds,
    )
    return report, load_seconds


def _write_report(report: ValidationReport, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": report.status,
        "knowledge_graph": report.knowledge_graph,
        "report_path": report.report_path,
        "engine": report.engine,
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
    print(f"Validation {report.status} (engine={report.engine}).")
    print(f"Knowledge graph: {report.knowledge_graph}")
    print(f"Report written to: {report.report_path}")
    if report.load_seconds is not None:
        print(f"Load duration: {report.load_seconds:.4f}s")
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
