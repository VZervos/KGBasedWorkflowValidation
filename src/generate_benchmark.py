"""Generate corrupted benchmark datasets for validation-rule evaluation.

Takes a clean XES log and injects intentional faults targeting R1/R2/R3.

Because some PROV relations are created during conversion (not present as XES
attributes), corruptions are applied where they actually produce rule violations:

- R2: remove ``time:timestamp`` from random XES events, then convert
- R1: remove ``wf:belongsToCase`` from random activities in the generated KG
- R3: break temporal order on random ``prov:wasInformedBy`` edges in the KG
  (XES timestamp edits alone cannot create R3 violations because conversion
  re-sorts events by time)

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

from rdflib import Graph, Literal
from rdflib.namespace import PROV, RDF, XSD

from src.xes_to_prov_kg import WF, convert_xes_to_prov_kg

DEFAULT_BENCHMARK_CONFIG = Path(__file__).resolve().parent.parent / "benchmark.ini"
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


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
    r1: RuleCorruptionConfig
    r2: RuleCorruptionConfig
    r3: RuleCorruptionConfig


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
    if not input_value:
        raise ValueError("Config option 'input' is required in [benchmark].")

    base_dir = config_path.parent
    return BenchmarkConfig(
        config_path=config_path,
        input_path=_resolve_path(base_dir, input_value),
        output_dir=_resolve_path(base_dir, output_value),
        seed=int(seed_raw) if seed_raw else None,
        r1=_load_rule_corruption(parser, "r1"),
        r2=_load_rule_corruption(parser, "r2"),
        r3=_load_rule_corruption(parser, "r3"),
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


def _write_xes(root: ET.Element, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    xml_bytes = ET.tostring(root, encoding="utf-8")
    text = xml_bytes.decode("utf-8")
    if not text.startswith("<?xml"):
        text = '<?xml version="1.0" encoding="UTF-8" ?>\n' + text
    path.write_text(text, encoding="utf-8")


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


def _parse_xsd_datetime(value: Literal) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _apply_r3_kg(
    graph: Graph,
    *,
    target_count: int,
    rng: random.Random,
    records: list[CorruptionRecord],
) -> tuple[int, int]:
    edges = []
    for later, _, earlier in graph.triples((None, PROV.wasInformedBy, None)):
        later_times = list(graph.objects(later, PROV.startedAtTime))
        earlier_times = list(graph.objects(earlier, PROV.startedAtTime))
        if later_times and earlier_times:
            edges.append((later, earlier, later_times[0], earlier_times[0]))

    chosen = rng.sample(edges, k=min(target_count, len(edges)))
    applied = 0
    for later, earlier, _later_time_snapshot, _earlier_time_snapshot in chosen:
        earlier_times_now = list(graph.objects(earlier, PROV.startedAtTime))
        later_times_now = list(graph.objects(later, PROV.startedAtTime))
        if not earlier_times_now or not later_times_now:
            continue

        earlier_time = earlier_times_now[0]
        later_time_before = later_times_now[0]
        earlier_dt = _parse_xsd_datetime(earlier_time)
        broken_dt = earlier_dt - timedelta(seconds=rng.randint(1, 3600))
        broken_literal = Literal(broken_dt.isoformat(), datatype=XSD.dateTime)

        for old in list(graph.objects(later, PROV.startedAtTime)):
            graph.remove((later, PROV.startedAtTime, old))
        for old in list(graph.objects(later, PROV.endedAtTime)):
            graph.remove((later, PROV.endedAtTime, old))
        graph.add((later, PROV.startedAtTime, broken_literal))
        graph.add((later, PROV.endedAtTime, broken_literal))

        records.append(
            CorruptionRecord(
                rule_id="R3",
                action="broke_wasInformedBy_temporal_order",
                details={
                    "later_activity": str(later),
                    "earlier_activity": str(earlier),
                    "later_time_before": str(later_time_before),
                    "earlier_time": str(earlier_time),
                    "later_time_after": str(broken_literal),
                },
            )
        )
        applied += 1
    return len(edges), applied


def _build_run_name(cfg: BenchmarkConfig, stamp: str) -> str:
    parts = ["bench"]
    if cfg.r1.enabled:
        parts.append("r1")
    if cfg.r2.enabled:
        parts.append("r2")
    if cfg.r3.enabled:
        parts.append("r3")
    parts.append(stamp)
    return "_".join(parts)


def _parse_xes(path: Path) -> ET.Element:
    if path.suffix == ".gz":
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "input.xes"
            with gzip.open(path, "rb") as src, tmp_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            return ET.parse(tmp_path).getroot()
    return ET.parse(path).getroot()


def generate_benchmark(cfg: BenchmarkConfig) -> BenchmarkStats:
    if not cfg.input_path.is_file():
        raise FileNotFoundError(f"Input XES not found: {cfg.input_path}")
    if not (cfg.r1.enabled or cfg.r2.enabled or cfg.r3.enabled):
        raise ValueError("Enable at least one of [r1], [r2], [r3].")

    started_at = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = _build_run_name(cfg, stamp)
    run_dir = cfg.output_dir / run_name
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
    convert_xes_to_prov_kg(corrupted_xes, corrupted_ttl)

    graph = Graph()
    graph.parse(corrupted_ttl)

    r1_eligible = sum(
        1
        for activity in graph.subjects(RDF.type, PROV.Activity)
        if list(graph.objects(activity, WF.belongsToCase))
    )
    r1_target = _resolve_target_count(
        cfg.r1,
        xes_line_count=xes_line_count,
        eligible_count=r1_eligible,
        rule_id="R1",
    )
    r1_applied = 0
    if cfg.r1.enabled:
        r1_eligible, r1_applied = _apply_r1_kg(
            graph, target_count=r1_target, rng=rng, records=records
        )

    r3_eligible = sum(
        1
        for later, _, earlier in graph.triples((None, PROV.wasInformedBy, None))
        if list(graph.objects(later, PROV.startedAtTime))
        and list(graph.objects(earlier, PROV.startedAtTime))
    )
    r3_target = _resolve_target_count(
        cfg.r3,
        xes_line_count=xes_line_count,
        eligible_count=r3_eligible,
        rule_id="R3",
    )
    r3_applied = 0
    if cfg.r3.enabled:
        r3_eligible, r3_applied = _apply_r3_kg(
            graph, target_count=r3_target, rng=rng, records=records
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
        },
        applied={
            "r1": {
                "eligible": r1_eligible,
                "target": r1_target,
                "applied": r1_applied,
            },
            "r2": {
                "eligible": r2_eligible,
                "target": r2_target,
                "applied": r2_applied,
            },
            "r3": {
                "eligible": r3_eligible,
                "target": r3_target,
                "applied": r3_applied,
            },
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
                "Conversion re-sorts events by timestamp, so R3 faults are injected "
                "on the KG by making later.startedAtTime < earlier.startedAtTime "
                "while keeping wasInformedBy."
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
    for rule_id, info in stats.applied.items():
        print(
            f"- {rule_id.upper()}: eligible={info['eligible']}, "
            f"target={info['target']}, applied={info['applied']}"
        )
    print(f"Statistics: {stats.outputs['statistics']}")
    return stats


def main() -> None:
    run_from_config()


if __name__ == "__main__":
    main()
