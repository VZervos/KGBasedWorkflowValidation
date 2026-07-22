"""Generate corrupted benchmark datasets for validation-rule evaluation.

Takes a clean XES log and injects intentional faults targeting R1–R6 / R5B.

Because some PROV relations are created during conversion (not present as XES
attributes), corruptions are applied where they actually produce rule violations:

- R2: remove ``time:timestamp`` from random XES events, then convert
- R1: remove ``wf:belongsToCase`` from random activities in the generated KG
- R3: remove ``prov:wasAssociatedWith`` from random activities in the KG
- R4: break temporal order on random ``wasInformedBy`` edges
  (``later.startedAtTime < earlier``)
- R5: rewrite ``Payment Handled`` resource away from SYSTEM to a random
  invalid / nonexistent value
- R5B: set ``Payment Handled`` role to EMPLOYEE
- R6: scramble order, insert a bogus stage, or remove ``wasInformedBy`` links
  (chosen at random per payment)

When ``count`` is set, that many eligible items are corrupted (or all if fewer
exist). When ``percent`` is set, the target is
``floor(percent / 100 * xes_line_count)``, capped by eligible items.
"""

from __future__ import annotations

import configparser
import gzip
import json
import random
import shutil
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from urllib.parse import quote

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import PROV, RDF, RDFS, XSD

from src.xes_to_prov_kg import ATTR, BASE, WF, convert_xes_to_prov_kg

DEFAULT_BENCHMARK_CONFIG = Path(__file__).resolve().parent.parent / "benchmark.ini"
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}

RESOURCE_PRED = ATTR["xes-attr_org_resource"]
ROLE_PRED = ATTR["xes-attr_org_role"]
PAYMENT_HANDLED = Literal("Payment Handled")
REQUEST_PAYMENT = Literal("Request Payment")
FINAL_APPROVAL = Literal("Declaration FINAL_APPROVED by SUPERVISOR")
SUBMISSION = Literal("Declaration SUBMITTED by EMPLOYEE")


@dataclass(frozen=True)
class RuleCorruptionConfig:
    enabled: bool
    count: int | None = None
    percent: float | None = None


@dataclass(frozen=True)
class BenchmarkConfig:
    config_path: Path
    input_path: Path
    output_dir: Path
    seed: int | None
    label: str
    r1: RuleCorruptionConfig
    r2: RuleCorruptionConfig
    r3: RuleCorruptionConfig
    r4: RuleCorruptionConfig
    r5: RuleCorruptionConfig
    r5b: RuleCorruptionConfig
    r6: RuleCorruptionConfig

    def enabled_rule_ids(self) -> list[str]:
        mapping = (
            ("r1", self.r1),
            ("r2", self.r2),
            ("r3", self.r3),
            ("r4", self.r4),
            ("r5", self.r5),
            ("r5b", self.r5b),
            ("r6", self.r6),
        )
        return [rule_id for rule_id, cfg in mapping if cfg.enabled]


@dataclass
class CorruptionRecord:
    rule_id: str
    action: str
    details: dict[str, str]


@dataclass
class BenchmarkStats:
    run_name: str
    run_dir: str
    input: str
    seed: int | None
    xes_line_count: int
    started_at: str
    finished_at: str
    requested: dict
    applied: dict
    corruptions: list[CorruptionRecord] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)


def _resolve_path(base_dir: Path, path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _parse_bool(value: str, *, option: str) -> bool:
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"Config option '{option}' must be true/false, got: {value!r}")


def _tag(elem: ET.Element) -> str:
    return elem.tag.rsplit("}", 1)[-1]


def _count_lines(path: Path) -> int:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def _resolve_target_count(
    rule_cfg: RuleCorruptionConfig,
    *,
    xes_line_count: int,
    eligible_count: int,
    rule_id: str,
) -> int:
    if not rule_cfg.enabled:
        return 0
    if rule_cfg.count is not None and rule_cfg.percent is not None:
        raise ValueError(
            f"[{rule_id.lower()}] set either 'count' or 'percent', not both."
        )
    if rule_cfg.count is None and rule_cfg.percent is None:
        raise ValueError(
            f"[{rule_id.lower()}] is enabled but neither 'count' nor 'percent' is set."
        )

    if rule_cfg.count is not None:
        requested = max(0, int(rule_cfg.count))
    else:
        assert rule_cfg.percent is not None
        if rule_cfg.percent < 0:
            raise ValueError(f"[{rule_id.lower()}] percent must be >= 0.")
        requested = int(xes_line_count * (rule_cfg.percent / 100.0))

    return min(requested, eligible_count)


def _load_rule_corruption(
    parser: configparser.ConfigParser,
    section: str,
) -> RuleCorruptionConfig:
    if section not in parser:
        return RuleCorruptionConfig(enabled=False)

    sec = parser[section]
    enabled = _parse_bool(sec.get("enabled", "false"), option=f"{section}.enabled")
    count_raw = sec.get("count", "").strip()
    percent_raw = sec.get("percent", "").strip()
    count = int(count_raw) if count_raw else None
    percent = float(percent_raw) if percent_raw else None
    return RuleCorruptionConfig(enabled=enabled, count=count, percent=percent)


def load_benchmark_config(
    config_path: Path = DEFAULT_BENCHMARK_CONFIG,
) -> BenchmarkConfig:
    config_path = config_path.resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Benchmark config not found: {config_path}")

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(config_path, encoding="utf-8")
    if "benchmark" not in parser:
        raise ValueError("Missing [benchmark] section.")

    section = parser["benchmark"]
    input_value = section.get("input", "").strip()
    output_value = section.get("output_dir", "benchmarks").strip()
    seed_raw = section.get("seed", "").strip()
    label_value = section.get("label", "").strip()
    if not input_value:
        raise ValueError("Config option 'input' is required in [benchmark].")

    base_dir = config_path.parent
    output_dir = _resolve_path(base_dir, output_value)
    label = label_value or output_dir.name
    return BenchmarkConfig(
        config_path=config_path,
        input_path=_resolve_path(base_dir, input_value),
        output_dir=output_dir,
        seed=int(seed_raw) if seed_raw else None,
        label=label,
        r1=_load_rule_corruption(parser, "r1"),
        r2=_load_rule_corruption(parser, "r2"),
        r3=_load_rule_corruption(parser, "r3"),
        r4=_load_rule_corruption(parser, "r4"),
        r5=_load_rule_corruption(parser, "r5"),
        r5b=_load_rule_corruption(parser, "r5b"),
        r6=_load_rule_corruption(parser, "r6"),
    )


def _iter_events(root: ET.Element):
    for trace in root:
        if _tag(trace) != "trace":
            continue
        trace_id = "(unknown)"
        for child in trace:
            if (
                _tag(child) in {"string", "date", "int", "float", "boolean"}
                and child.get("key") == "id"
                and child.get("value")
            ):
                trace_id = child.get("value", "(unknown)")
                break
        for event in trace:
            if _tag(event) == "event":
                yield trace_id, event


def _event_id(event: ET.Element) -> str:
    for child in event:
        if child.get("key") == "id" and child.get("value"):
            return child.get("value", "")
    return "(unknown)"


def _find_timestamp_nodes(event: ET.Element) -> list[ET.Element]:
    return [
        child
        for child in list(event)
        if _tag(child) in {"string", "date", "int", "float", "boolean"}
        and child.get("key") == "time:timestamp"
    ]


def _write_xes(root: ET.Element, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    xml_bytes = ET.tostring(root, encoding="utf-8")
    text = xml_bytes.decode("utf-8")
    if not text.startswith("<?xml"):
        text = '<?xml version="1.0" encoding="UTF-8" ?>\n' + text
    path.write_text(text, encoding="utf-8")


def _parse_xes(path: Path) -> ET.Element:
    if path.suffix == ".gz":
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "input.xes"
            with gzip.open(path, "rb") as src, tmp_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            return ET.parse(tmp_path).getroot()
    return ET.parse(path).getroot()


def _parse_xsd_datetime(value: Literal) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _activities_with_label(graph: Graph, label: Literal) -> list:
    return [
        activity
        for activity in graph.subjects(RDF.type, PROV.Activity)
        if label in set(graph.objects(activity, RDFS.label))
    ]


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


def _find_payment_milestones(graph: Graph, payment) -> tuple | None:
    """Return (payment, request, approval, submission, case) for a valid R6 chain."""
    cases = list(graph.objects(payment, WF.belongsToCase))
    if len(cases) != 1:
        return None
    case = cases[0]
    reachable = _ancestors(graph, payment)
    requests = [
        node
        for node in reachable
        if REQUEST_PAYMENT in set(graph.objects(node, RDFS.label))
        and case in set(graph.objects(node, WF.belongsToCase))
    ]
    for request in requests:
        request_reachable = _ancestors(graph, request)
        approvals = [
            node
            for node in request_reachable
            if FINAL_APPROVAL in set(graph.objects(node, RDFS.label))
            and case in set(graph.objects(node, WF.belongsToCase))
        ]
        for approval in approvals:
            approval_reachable = _ancestors(graph, approval)
            submissions = [
                node
                for node in approval_reachable
                if SUBMISSION in set(graph.objects(node, RDFS.label))
                and case in set(graph.objects(node, WF.belongsToCase))
            ]
            if submissions:
                return payment, request, approval, submissions[0], case
    return None


def _has_valid_payment_chain(graph: Graph, payment) -> bool:
    return _find_payment_milestones(graph, payment) is not None


def _clear_was_informed_by(graph: Graph, activity) -> list:
    earlier = list(graph.objects(activity, PROV.wasInformedBy))
    for node in earlier:
        graph.remove((activity, PROV.wasInformedBy, node))
    return earlier


def _corrupt_r6_scramble(
    graph: Graph,
    *,
    payment,
    request,
    approval,
    submission,
    case,
    rng: random.Random,
) -> CorruptionRecord:
    """Rewire milestones into an invalid order, e.g. payment → submission → approval."""
    patterns = (
        (payment, submission, approval, request),
        (payment, approval, request, submission),
        (payment, submission, request, approval),
        (payment, approval, submission, request),
    )
    chain = patterns[rng.randrange(len(patterns))]

    before = {
        "payment": str(payment),
        "request": str(request),
        "approval": str(approval),
        "submission": str(submission),
        "payment_wasInformedBy": "; ".join(
            str(n) for n in graph.objects(payment, PROV.wasInformedBy)
        ),
        "request_wasInformedBy": "; ".join(
            str(n) for n in graph.objects(request, PROV.wasInformedBy)
        ),
        "approval_wasInformedBy": "; ".join(
            str(n) for n in graph.objects(approval, PROV.wasInformedBy)
        ),
    }

    for node in (payment, request, approval, submission):
        _clear_was_informed_by(graph, node)

    # chain[0] informed by chain[1] informed by chain[2] informed by chain[3]
    for later, earlier in zip(chain, chain[1:]):
        graph.add((later, PROV.wasInformedBy, earlier))

    return CorruptionRecord(
        rule_id="R6",
        action="scrambled_payment_provenance_order",
        details={
            **before,
            "case": str(case),
            "new_order": " -> ".join(str(n) for n in chain),
        },
    )


def _corrupt_r6_insert_bogus_stage(
    graph: Graph,
    *,
    payment,
    request,
    approval,
    submission,
    case,
    rng: random.Random,
) -> CorruptionRecord:
    """Insert a fake activity that replaces the real Request Payment hop."""
    fake_id = f"bogus_stage_{rng.randint(100000, 999999)}"
    fake = URIRef(f"{BASE}activity/{quote(fake_id, safe='')}")
    fake_label = Literal(
        rng.choice(
            (
                "Bogus Intermediate Stage",
                "Fictional Approval Step",
                "Nonexistent Workflow Activity",
            )
        )
    )

    payment_earlier = _clear_was_informed_by(graph, payment)
    request_earlier = list(graph.objects(request, PROV.wasInformedBy))

    # Detach Request Payment from the ancestry of Payment Handled.
    graph.add((fake, RDF.type, PROV.Activity))
    graph.add((fake, RDFS.label, fake_label))
    graph.add((fake, WF.belongsToCase, case))
    graph.add((payment, PROV.wasInformedBy, fake))

    mode = rng.choice(("dead_end", "skip_request", "wrong_order_via_fake"))
    if mode == "dead_end":
        # Payment → Fake (no further links): chain cannot reach Request Payment.
        after_path = f"{payment} -> {fake}"
    elif mode == "skip_request":
        # Payment → Fake → Approval → … so Request is skipped entirely.
        _clear_was_informed_by(graph, fake)
        graph.add((fake, PROV.wasInformedBy, approval))
        after_path = f"{payment} -> {fake} -> {approval}"
    else:
        # Payment → Fake → Submission → Approval (scrambled via fake).
        _clear_was_informed_by(graph, fake)
        graph.add((fake, PROV.wasInformedBy, submission))
        submission_earlier = _clear_was_informed_by(graph, submission)
        graph.add((submission, PROV.wasInformedBy, approval))
        after_path = f"{payment} -> {fake} -> {submission} -> {approval}"
        request_earlier = submission_earlier  # for logging only

    return CorruptionRecord(
        rule_id="R6",
        action="inserted_bogus_payment_stage",
        details={
            "payment": str(payment),
            "request": str(request),
            "approval": str(approval),
            "submission": str(submission),
            "case": str(case),
            "bogus_activity": str(fake),
            "bogus_label": str(fake_label),
            "mode": mode,
            "payment_wasInformedBy_before": "; ".join(str(n) for n in payment_earlier),
            "request_wasInformedBy": "; ".join(str(n) for n in request_earlier),
            "path_after": after_path,
        },
    )


def _corrupt_r6_remove_links(
    graph: Graph,
    *,
    payment,
    request,
    approval,
    submission,
    case,
) -> CorruptionRecord:
    """Break the chain by removing Payment Handled's wasInformedBy link(s)."""
    earlier = _clear_was_informed_by(graph, payment)
    return CorruptionRecord(
        rule_id="R6",
        action="removed_payment_wasInformedBy",
        details={
            "payment": str(payment),
            "request": str(request),
            "approval": str(approval),
            "submission": str(submission),
            "case": str(case),
            "removed_earlier": "; ".join(str(n) for n in earlier),
        },
    )


def _apply_r6_kg(
    graph: Graph,
    *,
    target_count: int,
    rng: random.Random,
    records: list[CorruptionRecord],
) -> tuple[int, int]:
    eligible = [
        activity
        for activity in _activities_with_label(graph, PAYMENT_HANDLED)
        if _has_valid_payment_chain(graph, activity)
    ]
    chosen = rng.sample(eligible, k=min(target_count, len(eligible)))
    applied = 0
    strategies = ("scramble", "bogus_stage", "remove_links")
    for activity in chosen:
        milestones = _find_payment_milestones(graph, activity)
        if milestones is None:
            continue
        payment, request, approval, submission, case = milestones
        strategy = rng.choice(strategies)
        if strategy == "scramble":
            record = _corrupt_r6_scramble(
                graph,
                payment=payment,
                request=request,
                approval=approval,
                submission=submission,
                case=case,
                rng=rng,
            )
        elif strategy == "bogus_stage":
            record = _corrupt_r6_insert_bogus_stage(
                graph,
                payment=payment,
                request=request,
                approval=approval,
                submission=submission,
                case=case,
                rng=rng,
            )
        else:
            record = _corrupt_r6_remove_links(
                graph,
                payment=payment,
                request=request,
                approval=approval,
                submission=submission,
                case=case,
            )
        records.append(record)
        applied += 1
    return len(eligible), applied


def _apply_r2_xes(
    root: ET.Element,
    *,
    target_count: int,
    rng: random.Random,
    records: list[CorruptionRecord],
) -> tuple[int, int]:
    eligible = [
        (trace_id, event, _find_timestamp_nodes(event))
        for trace_id, event in _iter_events(root)
        if _find_timestamp_nodes(event)
    ]
    chosen = rng.sample(eligible, k=min(target_count, len(eligible)))
    for trace_id, event, nodes in chosen:
        event_id = _event_id(event)
        removed_values = [node.get("value", "") for node in nodes]
        for node in nodes:
            event.remove(node)
        records.append(
            CorruptionRecord(
                rule_id="R2",
                action="removed_time_timestamp",
                details={
                    "trace_id": trace_id,
                    "event_id": event_id,
                    "removed_values": "; ".join(removed_values),
                },
            )
        )
    return len(eligible), len(chosen)


def _apply_r1_kg(
    graph: Graph,
    *,
    target_count: int,
    rng: random.Random,
    records: list[CorruptionRecord],
) -> tuple[int, int]:
    activities = [
        activity
        for activity in graph.subjects(RDF.type, PROV.Activity)
        if list(graph.objects(activity, WF.belongsToCase))
    ]
    chosen = rng.sample(activities, k=min(target_count, len(activities)))
    for activity in chosen:
        cases = list(graph.objects(activity, WF.belongsToCase))
        for case in cases:
            graph.remove((activity, WF.belongsToCase, case))
        records.append(
            CorruptionRecord(
                rule_id="R1",
                action="removed_belongsToCase",
                details={
                    "activity": str(activity),
                    "removed_cases": "; ".join(str(case) for case in cases),
                    "case_count_before": str(len(cases)),
                },
            )
        )
    return len(activities), len(chosen)


def _apply_r3_kg(
    graph: Graph,
    *,
    target_count: int,
    rng: random.Random,
    records: list[CorruptionRecord],
) -> tuple[int, int]:
    activities = [
        activity
        for activity in graph.subjects(RDF.type, PROV.Activity)
        if list(graph.objects(activity, PROV.wasAssociatedWith))
    ]
    chosen = rng.sample(activities, k=min(target_count, len(activities)))
    for activity in chosen:
        agents = list(graph.objects(activity, PROV.wasAssociatedWith))
        for agent in agents:
            graph.remove((activity, PROV.wasAssociatedWith, agent))
        records.append(
            CorruptionRecord(
                rule_id="R3",
                action="removed_wasAssociatedWith",
                details={
                    "activity": str(activity),
                    "removed_agents": "; ".join(str(agent) for agent in agents),
                },
            )
        )
    return len(activities), len(chosen)


INVALID_PAYMENT_RESOURCES = (
    "EMPLOYEE",
    "STAFF MEMBER",
    "SUPERVISOR",
    "PRE_APPROVER",
    "ADMIN",
    "UNKNOWN",
    "UNDEFINED",
    "NULL",
    "Fictional Payment Handler",
    "NONEXISTENT_HANDLER",
    "",
)


def _random_invalid_payment_resource(rng: random.Random) -> str:
    if rng.random() < 0.35:
        return f"BOGUS_RESOURCE_{rng.randint(1000, 9999)}"
    return rng.choice(INVALID_PAYMENT_RESOURCES)


def _apply_r4_break_order(
    graph: Graph,
    *,
    later,
    earlier,
    rng: random.Random,
) -> CorruptionRecord | None:
    earlier_times = list(graph.objects(earlier, PROV.startedAtTime))
    later_times = list(graph.objects(later, PROV.startedAtTime))
    if not earlier_times or not later_times:
        return None

    earlier_time = earlier_times[0]
    later_time_before = later_times[0]
    earlier_dt = _parse_xsd_datetime(earlier_time)
    broken_dt = earlier_dt - timedelta(seconds=rng.randint(1, 3600))
    broken_literal = Literal(broken_dt.isoformat(), datatype=XSD.dateTime)

    for old in list(graph.objects(later, PROV.startedAtTime)):
        graph.remove((later, PROV.startedAtTime, old))
    for old in list(graph.objects(later, PROV.endedAtTime)):
        graph.remove((later, PROV.endedAtTime, old))
    graph.add((later, PROV.startedAtTime, broken_literal))
    graph.add((later, PROV.endedAtTime, broken_literal))

    return CorruptionRecord(
        rule_id="R4",
        action="broke_wasInformedBy_temporal_order",
        details={
            "later_activity": str(later),
            "earlier_activity": str(earlier),
            "later_time_before": str(later_time_before),
            "earlier_time": str(earlier_time),
            "later_time_after": str(broken_literal),
        },
    )


def _apply_r4_remove_started_at_time(
    graph: Graph,
    *,
    later,
    earlier,
) -> CorruptionRecord | None:
    starts = list(graph.objects(later, PROV.startedAtTime))
    if not starts:
        return None

    ends = list(graph.objects(later, PROV.endedAtTime))
    # Keep an end time even if none existed (use former start).
    if not ends:
        graph.add((later, PROV.endedAtTime, starts[0]))
        ends = [starts[0]]

    for old in starts:
        graph.remove((later, PROV.startedAtTime, old))

    return CorruptionRecord(
        rule_id="R4",
        action="removed_startedAtTime_kept_endedAtTime",
        details={
            "later_activity": str(later),
            "earlier_activity": str(earlier),
            "removed_startedAtTime": "; ".join(str(t) for t in starts),
            "kept_endedAtTime": "; ".join(str(t) for t in ends),
        },
    )


def _apply_r4_kg(
    graph: Graph,
    *,
    target_count: int,
    rng: random.Random,
    records: list[CorruptionRecord],
) -> tuple[int, int]:
    edges = [
        (later, earlier)
        for later, _, earlier in graph.triples((None, PROV.wasInformedBy, None))
        if list(graph.objects(later, PROV.startedAtTime))
        and list(graph.objects(earlier, PROV.startedAtTime))
    ]
    rng.shuffle(edges)
    applied = 0
    for later, earlier in edges:
        if applied >= target_count:
            break
        record = _apply_r4_break_order(
            graph, later=later, earlier=earlier, rng=rng
        )
        if record is None:
            continue
        records.append(record)
        applied += 1
    return len(edges), applied


def _apply_r5_kg(
    graph: Graph,
    *,
    target_count: int,
    rng: random.Random,
    records: list[CorruptionRecord],
) -> tuple[int, int]:
    eligible = [
        activity
        for activity in _activities_with_label(graph, PAYMENT_HANDLED)
        if Literal("SYSTEM") in set(graph.objects(activity, RESOURCE_PRED))
    ]
    chosen = rng.sample(eligible, k=min(target_count, len(eligible)))
    for activity in chosen:
        old_resources = list(graph.objects(activity, RESOURCE_PRED))
        for old in old_resources:
            graph.remove((activity, RESOURCE_PRED, old))
        new_resource = _random_invalid_payment_resource(rng)
        graph.add((activity, RESOURCE_PRED, Literal(new_resource)))

        records.append(
            CorruptionRecord(
                rule_id="R5",
                action="changed_payment_resource_from_system",
                details={
                    "activity": str(activity),
                    "resource_before": "; ".join(str(r) for r in old_resources),
                    "resource_after": new_resource if new_resource else "(empty)",
                },
            )
        )
    return len(eligible), len(chosen)


def _apply_r5b_kg(
    graph: Graph,
    *,
    target_count: int,
    rng: random.Random,
    records: list[CorruptionRecord],
) -> tuple[int, int]:
    eligible = [
        activity
        for activity in _activities_with_label(graph, PAYMENT_HANDLED)
        if Literal("EMPLOYEE") not in set(graph.objects(activity, ROLE_PRED))
    ]
    chosen = rng.sample(eligible, k=min(target_count, len(eligible)))
    for activity in chosen:
        old_roles = list(graph.objects(activity, ROLE_PRED))
        for old in old_roles:
            graph.remove((activity, ROLE_PRED, old))
        graph.add((activity, ROLE_PRED, Literal("EMPLOYEE")))
        records.append(
            CorruptionRecord(
                rule_id="R5B",
                action="set_payment_role_to_employee",
                details={
                    "activity": str(activity),
                    "role_before": "; ".join(str(r) for r in old_roles) or "(none)",
                    "role_after": "EMPLOYEE",
                },
            )
        )
    return len(eligible), len(chosen)


def _build_run_name(cfg: BenchmarkConfig) -> str:
    """Stable, searchable names: bench_r1_full, bench_all_10declarations, ..."""
    rules = cfg.enabled_rule_ids()
    rule_part = "all" if len(rules) > 1 else rules[0]
    return f"bench_{rule_part}_{cfg.label}"


def _applied_entry(eligible: int, target: int, applied: int) -> dict[str, int]:
    return {"eligible": eligible, "target": target, "applied": applied}


def generate_benchmark(cfg: BenchmarkConfig) -> BenchmarkStats:
    if not cfg.input_path.is_file():
        raise FileNotFoundError(f"Input XES not found: {cfg.input_path}")
    enabled = cfg.enabled_rule_ids()
    if not enabled:
        raise ValueError(
            "Enable at least one of [r1], [r2], [r3], [r4], [r5], [r5b], [r6]."
        )

    started_at = datetime.now(timezone.utc).isoformat()
    run_name = _build_run_name(cfg)
    run_dir = cfg.output_dir / run_name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(cfg.seed)
    records: list[CorruptionRecord] = []
    xes_line_count = _count_lines(cfg.input_path)
    root = _parse_xes(cfg.input_path)

    r2_eligible = sum(
        1 for _trace_id, event in _iter_events(root) if _find_timestamp_nodes(event)
    )
    r2_target = _resolve_target_count(
        cfg.r2,
        xes_line_count=xes_line_count,
        eligible_count=r2_eligible,
        rule_id="R2",
    )
    r2_applied = 0
    if cfg.r2.enabled:
        r2_eligible, r2_applied = _apply_r2_xes(
            root, target_count=r2_target, rng=rng, records=records
        )

    stem = cfg.input_path.name.replace(".xes.gz", "").replace(".xes", "")
    corrupted_xes = run_dir / f"{stem}.corrupted.xes"
    corrupted_ttl = run_dir / f"{stem}.corrupted.prov.ttl"
    stats_path = run_dir / "statistics.json"

    _write_xes(root, corrupted_xes)
    conversion = convert_xes_to_prov_kg(corrupted_xes, corrupted_ttl)

    graph = Graph()
    graph.parse(corrupted_ttl)

    def run_kg_rule(rule_id: str, rule_cfg: RuleCorruptionConfig, apply_fn, eligible_fn):
        eligible = eligible_fn()
        target = _resolve_target_count(
            rule_cfg,
            xes_line_count=xes_line_count,
            eligible_count=eligible,
            rule_id=rule_id,
        )
        applied = 0
        if rule_cfg.enabled:
            eligible, applied = apply_fn(
                graph, target_count=target, rng=rng, records=records
            )
        return eligible, target, applied

    r1_eligible, r1_target, r1_applied = run_kg_rule(
        "R1",
        cfg.r1,
        _apply_r1_kg,
        lambda: sum(
            1
            for activity in graph.subjects(RDF.type, PROV.Activity)
            if list(graph.objects(activity, WF.belongsToCase))
        ),
    )
    r3_eligible, r3_target, r3_applied = run_kg_rule(
        "R3",
        cfg.r3,
        _apply_r3_kg,
        lambda: sum(
            1
            for activity in graph.subjects(RDF.type, PROV.Activity)
            if list(graph.objects(activity, PROV.wasAssociatedWith))
        ),
    )
    r5_eligible, r5_target, r5_applied = run_kg_rule(
        "R5",
        cfg.r5,
        _apply_r5_kg,
        lambda: sum(
            1
            for activity in _activities_with_label(graph, PAYMENT_HANDLED)
            if Literal("SYSTEM") in set(graph.objects(activity, RESOURCE_PRED))
        ),
    )
    r5b_eligible, r5b_target, r5b_applied = run_kg_rule(
        "R5B",
        cfg.r5b,
        _apply_r5b_kg,
        lambda: sum(
            1
            for activity in _activities_with_label(graph, PAYMENT_HANDLED)
            if Literal("EMPLOYEE") not in set(graph.objects(activity, ROLE_PRED))
        ),
    )
    # R6 before R4: R6 rewires wasInformedBy edges; applying R4 afterward keeps
    # temporal breaks on the final graph topology used at validation time.
    r6_eligible, r6_target, r6_applied = run_kg_rule(
        "R6",
        cfg.r6,
        _apply_r6_kg,
        lambda: sum(
            1
            for activity in _activities_with_label(graph, PAYMENT_HANDLED)
            if _has_valid_payment_chain(graph, activity)
        ),
    )
    r4_eligible, r4_target, r4_applied = run_kg_rule(
        "R4",
        cfg.r4,
        _apply_r4_kg,
        lambda: sum(
            1
            for later, _, earlier in graph.triples((None, PROV.wasInformedBy, None))
            if list(graph.objects(later, PROV.startedAtTime))
            and list(graph.objects(earlier, PROV.startedAtTime))
        ),
    )

    graph.serialize(destination=str(corrupted_ttl), format="turtle")
    finished_at = datetime.now(timezone.utc).isoformat()

    stats = BenchmarkStats(
        run_name=run_name,
        run_dir=str(run_dir),
        input=str(cfg.input_path),
        seed=cfg.seed,
        xes_line_count=xes_line_count,
        started_at=started_at,
        finished_at=finished_at,
        requested={
            "r1": asdict(cfg.r1),
            "r2": asdict(cfg.r2),
            "r3": asdict(cfg.r3),
            "r4": asdict(cfg.r4),
            "r5": asdict(cfg.r5),
            "r5b": asdict(cfg.r5b),
            "r6": asdict(cfg.r6),
        },
        applied={
            "r1": _applied_entry(r1_eligible, r1_target, r1_applied),
            "r2": _applied_entry(r2_eligible, r2_target, r2_applied),
            "r3": _applied_entry(r3_eligible, r3_target, r3_applied),
            "r4": _applied_entry(r4_eligible, r4_target, r4_applied),
            "r5": _applied_entry(r5_eligible, r5_target, r5_applied),
            "r5b": _applied_entry(r5b_eligible, r5b_target, r5b_applied),
            "r6": _applied_entry(r6_eligible, r6_target, r6_applied),
        },
        corruptions=records,
        outputs={
            "corrupted_xes": str(corrupted_xes),
            "corrupted_knowledge_graph": str(corrupted_ttl),
            "statistics": str(stats_path),
        },
    )

    payload = {
        "run_name": stats.run_name,
        "run_dir": stats.run_dir,
        "input": stats.input,
        "seed": stats.seed,
        "xes_line_count": stats.xes_line_count,
        "started_at": stats.started_at,
        "finished_at": stats.finished_at,
        "conversion": {
            "trace_count": conversion.stats.trace_count,
            "event_count": conversion.stats.event_count,
            "triple_count": conversion.stats.triple_count,
            "agent_count": conversion.stats.agent_count,
            "duration_seconds": conversion.stats.duration_seconds,
            "xes_lines_parsed": conversion.stats.xes_lines_parsed,
        },
        "notes": {
            "r1": (
                "wf:belongsToCase is created during conversion, so R1 faults are "
                "injected on the generated KG by removing belongsToCase links."
            ),
            "r2": (
                "time:timestamp attributes are removed from random XES events "
                "before conversion, so activities lack prov:startedAtTime."
            ),
            "r3": (
                "prov:wasAssociatedWith is created during conversion, so R3 faults "
                "are injected on the KG by removing agent associations."
            ),
            "r4": (
                "R4 faults are injected on the KG by breaking wasInformedBy "
                "temporal order (later.startedAtTime < earlier)."
            ),
            "r5": (
                "Payment Handled activities that use SYSTEM get a random invalid "
                "attr:xes-attr_org_resource (known roles, empty, or invented "
                "BOGUS_RESOURCE_* values)."
            ),
            "r5b": (
                "Payment Handled activities have their org:role rewritten to "
                "EMPLOYEE."
            ),
            "r6": (
                "Payment Handled activities with a valid provenance chain are "
                "corrupted by randomly choosing one of: scramble milestone "
                "wasInformedBy order; insert a bogus intermediate activity; "
                "or remove Payment Handled's wasInformedBy link(s)."
            ),
            "percent": (
                "When percent is set, target count = floor(percent/100 * xes_line_count), "
                "capped by the number of eligible items for that rule."
            ),
        },
        "requested": stats.requested,
        "applied": stats.applied,
        "corruption_count": len(records),
        "corruptions": [asdict(record) for record in records],
        "outputs": stats.outputs,
    }
    stats_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return stats


def run_from_config(config_path: Path | None = None) -> BenchmarkStats:
    cfg = load_benchmark_config(config_path or DEFAULT_BENCHMARK_CONFIG)
    stats = generate_benchmark(cfg)
    print(f"Benchmark written to {stats.run_dir}")
    print(f"XES lines: {stats.xes_line_count}")
    print(f"Corruptions applied: {len(stats.corruptions)}")
    for rule_id in cfg.enabled_rule_ids():
        info = stats.applied[rule_id]
        print(
            f"- {rule_id.upper()}: eligible={info['eligible']}, "
            f"target={info['target']}, applied={info['applied']}"
        )
    print(f"Statistics: {stats.outputs['statistics']}")
    return stats


def main() -> None:
    import sys

    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    run_from_config(config_path)


if __name__ == "__main__":
    main()
