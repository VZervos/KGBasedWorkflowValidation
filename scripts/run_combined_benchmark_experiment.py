"""Generate combined (all-rules) benchmarks, validate, verify, and extend the report."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.generate_benchmark import generate_benchmark, load_benchmark_config
from src.validate_kg import validate_knowledge_graph
from src.validation_rules import VALIDATION_RULES
from src.xes_to_prov_kg import load_graph

BENCH_ROOT = ROOT / "benchmarks"
OUT_ROOT = ROOT / "output" / "per_rule_validation"
REPORT_PATH = OUT_ROOT / "experiment_report.md"
REPORT_JSON = OUT_ROOT / "experiment_report.json"

RULES = ("r1", "r2", "r3", "r4", "r5", "r5b", "r6")
RULE_ID_MAP = {
    "r1": "R1",
    "r2": "R2",
    "r3": "R3",
    "r4": "R4",
    "r5": "R5",
    "r5b": "R5B",
    "r6": "R6",
}

BASELINE_R6_COUNT_FULL = 9

DATASETS = (
    {
        "name": "10declarations",
        "input": "../dataset/DomesticDeclarations.sample_10declarations.xes",
        "count": 5,
    },
    {
        "name": "full",
        "input": "../dataset/DomesticDeclarations.xes.gz",
        "count": 100,
    },
)


def _combined_ini(dataset: dict) -> str:
    sections = [
        "[benchmark]",
        f"input = {dataset['input']}",
        "output_dir = .",
        f"label = {dataset['name']}",
        "seed = 42",
        "",
    ]
    for r in RULES:
        sections.append(f"[{r}]")
        sections.append("enabled = true")
        sections.append(f"count = {dataset['count']}")
        sections.append("")
    return "\n".join(sections)


def _inject_key(rule_id: str, details: dict) -> str | None:
    if rule_id == "R2":
        event_id = details.get("event_id")
        if event_id:
            return (
                "http://kg.workflow.validation/activity/"
                + event_id.replace(" ", "_")
            )
        return details.get("activity")
    if rule_id == "R4":
        later = details.get("later_activity")
        earlier = details.get("earlier_activity")
        return f"{later}|{earlier}" if later and earlier else later
    if rule_id in {"R5", "R5B", "R6"}:
        return details.get("payment") or details.get("activity")
    return details.get("activity")


def _viol_key(rule_id: str, details: dict) -> str | None:
    if rule_id == "R4":
        activity = details.get("activity")
        earlier = details.get("earlier")
        return f"{activity}|{earlier}" if activity and earlier else activity
    if rule_id in {"R5", "R5B", "R6"}:
        return details.get("activity") or details.get("payment")
    return details.get("activity")


def _precision_recall(
    rule_id: str, corruptions: list[dict], violations: list[dict]
) -> dict:
    injected = {
        key
        for corr in corruptions
        if corr.get("rule_id") == rule_id
        for key in [_inject_key(rule_id, corr.get("details", {}))]
        if key
    }
    detected = {
        key
        for viol in violations
        for key in [_viol_key(rule_id, viol.get("details", {}))]
        if key
    }
    tp = len(injected & detected)
    fp = len(detected - injected)
    fn = len(injected - detected)
    precision = (tp / (tp + fp)) if (tp + fp) else None
    recall = (tp / (tp + fn)) if (tp + fn) else None
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
    }


def _verify_rule(
    *,
    dataset: str,
    rule_id: str,
    applied: int,
    requested: int,
    detected: int,
    pr: dict,
) -> tuple[bool, str]:
    """Combined benches expect collateral: detected >= applied, recall of injected == 1."""
    if applied != requested:
        return False, f"applied {applied} != requested {requested}"
    if detected < applied:
        return False, f"detected {detected} < applied {applied}"
    if pr.get("false_negatives", 0) != 0:
        return False, f"FN={pr['false_negatives']} (missed injected faults)"
    extra = detected - applied
    note = f"detected {detected} >= applied {applied}"
    if extra:
        note += f" (+{extra} collateral/baseline)"
    if dataset == "full" and rule_id == "R6" and extra < BASELINE_R6_COUNT_FULL:
        note += " (baseline may overlap injected set)"
    return True, note


def run_combined_for_dataset(dataset: dict) -> dict:
    cfg_path = BENCH_ROOT / f"_suite_{dataset['name']}_all.ini"
    cfg_path.write_text(_combined_ini(dataset), encoding="utf-8")

    print(f"[{dataset['name']}/ALL] generating...", flush=True)
    stats = generate_benchmark(load_benchmark_config(cfg_path))
    bench_stats = json.loads(
        Path(stats.outputs["statistics"]).read_text(encoding="utf-8")
    )
    ttl = Path(stats.outputs["corrupted_knowledge_graph"])

    print(f"[{dataset['name']}/ALL] loading KG...", flush=True)
    load_started = time.perf_counter()
    graph = load_graph(ttl)
    load_seconds = round(time.perf_counter() - load_started, 6)

    val_dir = OUT_ROOT / f"val_all_{dataset['name']}"
    val_dir.mkdir(parents=True, exist_ok=True)
    report_path = val_dir / "validation.json"

    print(f"[{dataset['name']}/ALL] validating all rules...", flush=True)
    report = validate_knowledge_graph(
        graph,
        knowledge_graph_path=ttl,
        report_path=report_path,
        rules=VALIDATION_RULES,
    )

    val_payload = json.loads(report_path.read_text(encoding="utf-8"))
    per_rule = []
    all_ok = True
    for rule in RULES:
        rule_id = RULE_ID_MAP[rule]
        applied = bench_stats["applied"][rule]["applied"]
        result = next(r for r in val_payload["results"] if r["rule_id"] == rule_id)
        corruptions = [
            c for c in bench_stats["corruptions"] if c["rule_id"] == rule_id
        ]
        pr = _precision_recall(rule_id, corruptions, result["violations"])
        ok, note = _verify_rule(
            dataset=dataset["name"],
            rule_id=rule_id,
            applied=applied,
            requested=dataset["count"],
            detected=result["violation_count"],
            pr=pr,
        )
        all_ok = all_ok and ok
        print(
            f"  [{rule_id}] {'PASS' if ok else 'FAIL'}: "
            f"applied={applied}, detected={result['violation_count']}, "
            f"P={pr['precision']}, R={pr['recall']} ({note})",
            flush=True,
        )
        per_rule.append(
            {
                "rule": rule_id,
                "applied": applied,
                "eligible": bench_stats["applied"][rule]["eligible"],
                "detected": result["violation_count"],
                "validation_seconds": result["duration_seconds"],
                "precision_recall": pr,
                "ok": ok,
                "note": note,
                "sample_injected": corruptions[:2],
                "issue_counts": _count_issues(result["violations"]),
            }
        )

    conversion = bench_stats.get("conversion") or {}
    return {
        "dataset": dataset["name"],
        "bench_dir": stats.run_dir,
        "bench_run_name": bench_stats.get("run_name"),
        "requested_count_per_rule": dataset["count"],
        "total_injected": sum(r["applied"] for r in per_rule),
        "total_detected": val_payload["total_violations"],
        "traces": conversion.get("trace_count"),
        "events": conversion.get("event_count"),
        "triples": conversion.get("triple_count"),
        "conversion_seconds": conversion.get("duration_seconds"),
        "load_seconds": load_seconds,
        "validation_seconds_total": report.duration_seconds,
        "ok": all_ok,
        "per_rule": per_rule,
        "validation_report": str(report_path),
        "sample_injected_all": bench_stats["corruptions"][:5],
    }


def _count_issues(violations: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in violations:
        issue = v.get("issue", "?")
        counts[issue] = counts.get(issue, 0) + 1
    return counts


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def extend_report(combined_cases: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    existing_md = (
        REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.is_file() else ""
    )
    existing_json: dict = {}
    if REPORT_JSON.is_file():
        existing_json = json.loads(REPORT_JSON.read_text(encoding="utf-8"))

    # Strip a previous combined section if re-running.
    marker = "## Combined all-rules benchmarks"
    if marker in existing_md:
        existing_md = existing_md.split(marker)[0].rstrip() + "\n\n"

    lines: list[str] = [marker, ""]
    lines.append(f"Updated: `{now}`")
    lines.append("")
    lines.append(
        "These benchmarks inject **all rules together** on one KG "
        "(same per-rule counts as the isolated experiments: 5 on 10declarations, "
        "100 on full; seed `42`). Validation then runs **all rules** on that KG."
    )
    lines.append("")
    lines.append(
        "Because corruptions interact, detected violations are expected to be "
        "**≥ injected** per rule (collateral). Entity-level recall of injected "
        "faults should still be 1.0; precision drops when collateral/baseline "
        "violations appear."
    )
    lines.append("")

    passed = sum(1 for c in combined_cases if c["ok"])
    lines.append(f"Combined suites passed verification: **{passed}/{len(combined_cases)}**.")
    lines.append("")

    lines.append("### Combined suite overview")
    lines.append("")
    lines.append(
        "| Dataset | Traces | Events | Triples | Conv (s) | Load (s) | Val total (s) | Injected | Detected | Status |"
    )
    lines.append(
        "|---------|--------|--------|---------|----------|----------|---------------|----------|----------|--------|"
    )
    for c in combined_cases:
        lines.append(
            "| {ds} | {tr} | {ev} | {tp} | {conv} | {load} | {val} | {inj} | {det} | {st} |".format(
                ds=c["dataset"],
                tr=_fmt(c.get("traces"), 0),
                ev=_fmt(c.get("events"), 0),
                tp=_fmt(c.get("triples"), 0),
                conv=_fmt(c.get("conversion_seconds")),
                load=_fmt(c.get("load_seconds")),
                val=_fmt(c.get("validation_seconds_total")),
                inj=_fmt(c.get("total_injected"), 0),
                det=_fmt(c.get("total_detected"), 0),
                st="PASS" if c["ok"] else "FAIL",
            )
        )
    lines.append("")

    lines.append("### Per-rule results on combined benchmarks")
    lines.append("")
    lines.append(
        "| Dataset | Rule | Injected | Detected | Extra | Val (s) | P | R | Status |"
    )
    lines.append(
        "|---------|------|----------|----------|-------|---------|---|---|--------|"
    )
    for c in combined_cases:
        for r in c["per_rule"]:
            pr = r["precision_recall"]
            extra = r["detected"] - r["applied"]
            lines.append(
                "| {ds} | {rule} | {inj} | {det} | {extra} | {val} | {p} | {rec} | {st} |".format(
                    ds=c["dataset"],
                    rule=r["rule"],
                    inj=r["applied"],
                    det=r["detected"],
                    extra=extra,
                    val=_fmt(r["validation_seconds"]),
                    p=_fmt(pr.get("precision")),
                    rec=_fmt(pr.get("recall")),
                    st="PASS" if r["ok"] else "FAIL",
                )
            )
    lines.append("")

    lines.append("### Comparison: isolated vs combined (detected counts)")
    lines.append("")
    lines.append(
        "Isolated = one-rule benchmarks from the earlier section. "
        "Combined extras are mainly collateral across rules "
        "(plus the 9 baseline R6 payments on full)."
    )
    lines.append("")
    isolated_by_key = {
        (case["dataset"], case["rule"]): case
        for case in existing_json.get("cases", [])
    }
    lines.append(
        "| Dataset | Rule | Isolated detected | Combined detected | Δ |"
    )
    lines.append("|---------|------|-------------------|-------------------|---|")
    for c in combined_cases:
        for r in c["per_rule"]:
            iso = isolated_by_key.get((c["dataset"], r["rule"]), {})
            iso_det = iso.get("violations_detected")
            delta = (
                r["detected"] - iso_det if isinstance(iso_det, int) else None
            )
            lines.append(
                f"| {c['dataset']} | {r['rule']} | {_fmt(iso_det, 0)} | "
                f"{r['detected']} | {_fmt(delta, 0)} |"
            )
    lines.append("")

    for c in combined_cases:
        lines.append(f"### Combined detail: {c['dataset']}")
        lines.append("")
        lines.append(f"- Benchmark: `{c['bench_dir']}`")
        lines.append(f"- Validation report: `{c['validation_report']}`")
        lines.append(
            f"- Size: traces={_fmt(c.get('traces'), 0)}, "
            f"events={_fmt(c.get('events'), 0)}, "
            f"triples={_fmt(c.get('triples'), 0)}"
        )
        lines.append(
            f"- Times: conversion={_fmt(c.get('conversion_seconds'))}s, "
            f"load={_fmt(c.get('load_seconds'))}s, "
            f"validation_total={_fmt(c.get('validation_seconds_total'))}s"
        )
        lines.append(
            f"- Totals: injected={c['total_injected']}, "
            f"detected={c['total_detected']}"
        )
        for r in c["per_rule"]:
            pr = r["precision_recall"]
            lines.append(
                f"- **{r['rule']}**: injected={r['applied']}, "
                f"detected={r['detected']}, "
                f"val={_fmt(r['validation_seconds'])}s, "
                f"P={_fmt(pr.get('precision'))}, R={_fmt(pr.get('recall'))}, "
                f"issues={r['issue_counts']} — {r['note']}"
            )
        lines.append("")
        if c.get("sample_injected_all"):
            lines.append("- Sample injected faults (first 5 across rules):")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(c["sample_injected_all"], indent=2))
            lines.append("```")
            lines.append("")

    lines.append("### Combined-benchmark notes")
    lines.append("")
    lines.append(
        "- **Verification criterion**: per rule, `detected >= applied` and "
        "entity-level recall of injected faults = 1.0 (no false negatives)."
    )
    lines.append(
        "- **Precision < 1** is expected here: collateral from other rules "
        "and (on full R6) the 9 pre-existing invalid payments count as FP "
        "relative to that rule's injection set."
    )
    lines.append(
        "- R2 XES timestamp removal can also feed R4 "
        "(`missing_startedAtTime_on_*`) as collateral."
    )
    lines.append("")

    REPORT_PATH.write_text(existing_md + "\n".join(lines), encoding="utf-8")
    existing_json["combined_updated_at"] = now
    existing_json["combined_cases"] = combined_cases
    REPORT_JSON.write_text(json.dumps(existing_json, indent=2), encoding="utf-8")
    print(f"Report extended: {REPORT_PATH}", flush=True)
    print(f"JSON updated: {REPORT_JSON}", flush=True)


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    combined_cases = []
    for dataset in DATASETS:
        print(f"\n=== Combined dataset: {dataset['name']} ===", flush=True)
        combined_cases.append(run_combined_for_dataset(dataset))

    extend_report(combined_cases)
    failed = [c for c in combined_cases if not c["ok"]]
    if failed:
        raise SystemExit(
            f"Combined verification failed for: "
            + ", ".join(c["dataset"] for c in failed)
        )
    print("\nAll combined experiments verified.", flush=True)


if __name__ == "__main__":
    main()
