"""Full experiment suite: regenerate all rules, validate, then all-rules.

Phases:
  isolated  — regenerate R1–R6 for both datasets; KG+DECLARE on R1–R4,
              KG-only on R5/R5B/R6; write experiment_report.*
  combined  — regenerate/validate all-rules benches, extend report
  all       — isolated then combined

Naming is stable: bench_<rule>_<dataset>, val_<rule>_<dataset>, val_all_<dataset>.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pm4py

from src.generate_benchmark import generate_benchmark, load_benchmark_config
from src.validate_declare_baseline import declare_model_for_rule, load_xes
from src.validate_kg import validate_knowledge_graph
from src.validation_rules import VALIDATION_RULES
from src.xes_to_prov_kg import load_graph

BENCH_ROOT = ROOT / "benchmarks"
OUT_ROOT = ROOT / "output" / "per_rule_validation"
REPORT_MD = OUT_ROOT / "experiment_report.md"
REPORT_JSON = OUT_ROOT / "experiment_report.json"

RULES = ("r1", "r2", "r3", "r4", "r5", "r5b", "r6")
DECLARE_RULES = frozenset({"r1", "r2", "r3", "r4"})
KG_ONLY_RULES = frozenset({"r5", "r5b", "r6"})
RULE_ID = {
    "r1": "R1",
    "r2": "R2",
    "r3": "R3",
    "r4": "R4",
    "r5": "R5",
    "r5b": "R5B",
    "r6": "R6",
}
MULTI_ROW = frozenset({"R2", "R4", "R6"})

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

COMPLEXITY = {
    "R1": "DECLARE existence / case-level submission presence",
    "R2": "DECLARE response / approval→request path",
    "R3": "DECLARE precedence / request before payment",
    "R4": "DECLARE succession / request↔payment",
    "R5": "O(P) Payment Handled resource check",
    "R5B": "O(P) Payment Handled role check",
    "R6": "O(P·E_case) payment provenance chain BFS",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rule_obj(rule_id: str):
    for rule in VALIDATION_RULES:
        if rule.rule_id == rule_id:
            return rule
    raise KeyError(rule_id)


def _case_from_uri(uri: str) -> str:
    suffix = uri.rsplit("/", 1)[-1]
    if suffix.startswith("declaration_"):
        return "declaration " + suffix[len("declaration_") :]
    return suffix.replace("_", " ", 1)


def _benchmark_ini(dataset: dict, rule: str | None) -> str:
    """rule=None means all rules enabled."""
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
        if rule is None or r == rule:
            sections.append("enabled = true")
            sections.append(f"count = {dataset['count']}")
        else:
            sections.append("enabled = false")
        sections.append("")
    return "\n".join(sections)


def _injected_cases(corruptions: list[dict], rule_id: str) -> set[str]:
    cases = set()
    for corr in corruptions:
        if corr.get("rule_id") != rule_id:
            continue
        tid = (corr.get("details") or {}).get("trace_id")
        if tid:
            cases.add(str(tid))
    return cases


def _kg_cases(violations: list[dict]) -> set[str]:
    cases = set()
    for viol in violations:
        details = viol.get("details") or {}
        if "case" in details:
            cases.add(_case_from_uri(str(details["case"])))
    return cases


def _case_pr(injected: set[str], detected: set[str]) -> dict:
    tp = len(injected & detected)
    fp = len(detected - injected)
    fn = len(injected - detected)
    precision = tp / (tp + fp) if (tp + fp) else (1.0 if not detected else 0.0)
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "injected_cases": len(injected),
        "detected_cases": len(detected),
    }


def _entity_pr(rule_id: str, corruptions: list[dict], violations: list[dict]) -> dict:
    """Entity-level PR for R5/R5B/R6."""

    def inj_key(details: dict) -> str | None:
        return details.get("payment") or details.get("activity")

    def viol_key(details: dict) -> str | None:
        return details.get("activity") or details.get("payment")

    injected = {
        key
        for c in corruptions
        if c.get("rule_id") == rule_id
        for key in [inj_key(c.get("details") or {})]
        if key
    }
    detected = {
        key
        for v in violations
        for key in [viol_key(v.get("details") or {})]
        if key
    }
    tp = len(injected & detected)
    fp = len(detected - injected)
    fn = len(injected - detected)
    precision = tp / (tp + fp) if (tp + fp) else (1.0 if not detected else 0.0)
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
    }


def _run_declare_cases(xes_path: Path, rule_id: str) -> dict:
    started = time.perf_counter()
    log = load_xes(xes_path)
    model = declare_model_for_rule(rule_id)
    df = pm4py.conformance_declare(log, model, return_diagnostics_dataframe=True)
    duration = round(time.perf_counter() - started, 6)
    violated = {
        str(row["case_id"])
        for _, row in df.iterrows()
        if int(row.get("no_dev_total", 0) or 0) > 0
    }
    return {
        "status": "FAILED" if violated else "PASSED",
        "violated_cases": sorted(violated),
        "violated_case_count": len(violated),
        "deviation_total": int(df["no_dev_total"].sum()) if len(df) else 0,
        "duration_seconds": duration,
        "method": "pm4py.conformance_declare",
        "template": next(iter(model)),
    }


def _validate_kg_rule(ttl: Path, rule_id: str, val_dir: Path) -> tuple[dict, float, float]:
    val_dir.mkdir(parents=True, exist_ok=True)
    report_path = val_dir / "validation.json"
    load_started = time.perf_counter()
    graph = load_graph(ttl)
    load_seconds = round(time.perf_counter() - load_started, 6)
    report = validate_knowledge_graph(
        graph,
        knowledge_graph_path=ttl,
        report_path=report_path,
        rules=(_rule_obj(rule_id),),
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    return payload, load_seconds, report.duration_seconds


def _verify_isolated(rule_id: str, applied: int, row_count: int, case_pr: dict | None, entity_pr: dict | None) -> tuple[bool, str]:
    if applied == 0:
        return False, "no corruptions applied"
    if rule_id in {"R1", "R2", "R3", "R4"}:
        assert case_pr is not None
        if case_pr["false_negatives"] != 0:
            return False, f"case FN={case_pr['false_negatives']}"
        if case_pr["recall"] != 1.0:
            return False, f"case recall={case_pr['recall']}"
        # Detected cases may exceed injected (pre-existing clean-log violations).
        if case_pr["detected_cases"] < applied:
            return False, f"cases {case_pr['detected_cases']} < applied {applied}"
        if row_count < applied:
            return False, f"rows {row_count} < applied {applied}"
        extra = case_pr["detected_cases"] - applied
        note = f"cases={case_pr['detected_cases']} rows={row_count}"
        if extra:
            note += f" (+{extra} baseline/collateral cases)"
        return True, note
    # R5/R5B/R6
    assert entity_pr is not None
    if entity_pr["false_negatives"] != 0:
        return False, f"entity FN={entity_pr['false_negatives']}"
    if rule_id in MULTI_ROW:
        if row_count < applied:
            return False, f"rows {row_count} < applied {applied}"
        return True, f"rows={row_count} recall=1"
    if entity_pr["recall"] != 1.0:
        return False, f"recall={entity_pr['recall']}"
    return True, f"rows={row_count} P={entity_pr['precision']} R={entity_pr['recall']}"


def run_isolated_rule(dataset: dict, rule: str, *, regenerate: bool = True) -> dict:
    rule_id = RULE_ID[rule]
    bench_dir = BENCH_ROOT / f"bench_{rule}_{dataset['name']}"
    val_dir = OUT_ROOT / f"val_{rule}_{dataset['name']}"
    declare_dir = OUT_ROOT / f"declare_{rule}_{dataset['name']}"

    if regenerate:
        cfg_path = BENCH_ROOT / f"_suite_{dataset['name']}_{rule}.ini"
        cfg_path.write_text(_benchmark_ini(dataset, rule), encoding="utf-8")
        print(f"  [{dataset['name']}/{rule_id}] generating...", flush=True)
        stats = generate_benchmark(load_benchmark_config(cfg_path))
        bench_dir = Path(stats.run_dir)
    else:
        if not bench_dir.is_dir():
            raise FileNotFoundError(f"Missing benchmark: {bench_dir}")
        print(f"  [{dataset['name']}/{rule_id}] reusing {bench_dir.name}...", flush=True)

    stats_path = bench_dir / "statistics.json"
    bench_stats = json.loads(stats_path.read_text(encoding="utf-8"))
    ttl = Path(bench_stats["outputs"]["corrupted_knowledge_graph"])
    xes = Path(bench_stats["outputs"]["corrupted_xes"])
    applied = bench_stats["applied"][rule]["applied"]
    corruptions = [c for c in bench_stats["corruptions"] if c["rule_id"] == rule_id]
    conversion = bench_stats.get("conversion") or {}

    print(f"  [{dataset['name']}/{rule_id}] KG validating...", flush=True)
    kg_payload, load_seconds, _ = _validate_kg_rule(ttl, rule_id, val_dir)
    kg_result = kg_payload["results"][0]
    kg_rows = kg_result["violation_count"]
    kg_case_set = _kg_cases(kg_result.get("violations") or [])

    declare_info = None
    case_pr = None
    entity_pr = None
    if rule in DECLARE_RULES:
        print(f"  [{dataset['name']}/{rule_id}] DECLARE validating...", flush=True)
        declare_info = _run_declare_cases(xes, rule_id)
        declare_dir.mkdir(parents=True, exist_ok=True)
        (declare_dir / "declare.json").write_text(
            json.dumps(declare_info, indent=2), encoding="utf-8"
        )
        injected = _injected_cases(corruptions, rule_id)
        case_pr_kg = _case_pr(injected, kg_case_set)
        case_pr_dec = _case_pr(injected, set(declare_info["violated_cases"]))
        case_pr = {
            "kg": case_pr_kg,
            "declare": case_pr_dec,
            "sets_equal": kg_case_set == set(declare_info["violated_cases"]),
        }
        ok_kg, note_kg = _verify_isolated(rule_id, applied, kg_rows, case_pr_kg, None)
        ok_dec = case_pr_dec["false_negatives"] == 0 and case_pr_dec["recall"] == 1.0
        ok = ok_kg and ok_dec and case_pr["sets_equal"]
        note = (
            f"KG[{note_kg}]; DECLARE cases={declare_info['violated_case_count']} "
            f"devs={declare_info['deviation_total']}; sets_equal={case_pr['sets_equal']}"
        )
    else:
        entity_pr = _entity_pr(rule_id, corruptions, kg_result.get("violations") or [])
        ok, note = _verify_isolated(rule_id, applied, kg_rows, None, entity_pr)

    status = "PASS" if ok else "FAIL"
    print(
        f"  [{dataset['name']}/{rule_id}] {status}: applied={applied} "
        f"KG_rows={kg_rows} ({note})",
        flush=True,
    )
    return {
        "dataset": dataset["name"],
        "rule": rule_id,
        "bench_dir": str(bench_dir),
        "val_dir": str(val_dir),
        "applied": applied,
        "eligible": bench_stats["applied"][rule]["eligible"],
        "traces": conversion.get("trace_count"),
        "events": conversion.get("event_count"),
        "triples": conversion.get("triple_count"),
        "conversion_seconds": conversion.get("duration_seconds"),
        "load_seconds": load_seconds,
        "kg": {
            "rows": kg_rows,
            "duration_seconds": kg_result["duration_seconds"],
            "violated_cases": sorted(kg_case_set),
            "violated_case_count": len(kg_case_set),
            "status": kg_result["status"],
        },
        "declare": declare_info,
        "case_precision_recall": case_pr,
        "entity_precision_recall": entity_pr,
        "ok": ok,
        "status": status,
        "note": note,
        "complexity": COMPLEXITY[rule_id],
        "sample_injected": corruptions[:3],
        "regenerated": regenerate,
    }


def write_isolated_report(results: list[dict]) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    now = _now()
    passed = sum(1 for r in results if r["ok"])
    lines = [
        "# Benchmark experiment report",
        "",
        f"Generated: `{now}`",
        "",
        "## Setup",
        "",
        "- Datasets: **10declarations** (5 faults/rule) and **full** (100 faults/rule)",
        "- R1–R4: DECLARE-aligned control-flow (existence / response / precedence / succession);",
        "  faults injected in XES; compared with KG SPARQL **and** PM4Py DECLARE on **violated cases**",
        "- R5 / R5B / R6: KG-only domain rules (resource / role / provenance); no DECLARE",
        "- Seed: `42`",
        "",
        "## Isolated per-rule summary",
        "",
        f"Passed **{passed}/{len(results)}**.",
        "",
        "| Dataset | Rule | Traces | Events | Triples | Conv (s) | Load (s) | KG val (s) | Inj. | KG cases | KG rows | DECLARE cases | DECLARE (s) | Case P | Case R | Status |",
        "|---------|------|--------|--------|---------|----------|----------|------------|------|----------|---------|---------------|-------------|--------|--------|--------|",
    ]
    for r in results:
        dec = r.get("declare") or {}
        cpr = (r.get("case_precision_recall") or {}).get("kg") or r.get("entity_precision_recall") or {}
        # For KG-only use entity P/R in the Case columns for continuity
        if r["rule"] in {"R5", "R5B", "R6"}:
            p = cpr.get("precision")
            rec = cpr.get("recall")
            kg_cases = "n/a"
            dec_cases = "n/a"
            dec_s = "n/a"
        else:
            p = cpr.get("precision")
            rec = cpr.get("recall")
            kg_cases = r["kg"]["violated_case_count"]
            dec_cases = dec.get("violated_case_count", "n/a")
            dec_s = _fmt(dec.get("duration_seconds"))
        lines.append(
            f"| {r['dataset']} | {r['rule']} | {r['traces']} | {r['events']} | {r['triples']} | "
            f"{_fmt(r['conversion_seconds'])} | {_fmt(r['load_seconds'])} | "
            f"{_fmt(r['kg']['duration_seconds'])} | {r['applied']} | {kg_cases} | "
            f"{r['kg']['rows']} | {dec_cases} | {dec_s} | {_fmt(p)} | {_fmt(rec)} | {r['status']} |"
        )

    lines.extend(
        [
            "",
            "### Notes on counting",
            "",
            "- **Primary ground truth for R1–R4:** violated **cases** (injected `trace_id`).",
            "- KG may emit more **rows** than cases (e.g. R2 multiple approvals, R4 both succession halves).",
            "- DECLARE is scored on unfit cases for the single template of that rule.",
            "- R5–R6 use entity-level precision/recall (no DECLARE).",
            "",
            "### Timing / complexity",
            "",
            "| Rule | Complexity |",
            "|------|------------|",
        ]
    )
    for rid, text in COMPLEXITY.items():
        lines.append(f"| {rid} | {text} |")

    lines.extend(["", "## Per-rule details", ""])
    for r in results:
        lines.append(f"### {r['dataset']} / {r['rule']}")
        lines.append("")
        lines.append(f"- Benchmark: `{r['bench_dir']}`")
        lines.append(f"- Status: **{r['status']}** ({r['note']})")
        lines.append(
            f"- Size: traces={r['traces']}, events={r['events']}, triples={r['triples']}"
        )
        lines.append(
            f"- Times: conversion={_fmt(r['conversion_seconds'])}s, "
            f"load={_fmt(r['load_seconds'])}s, "
            f"KG val={_fmt(r['kg']['duration_seconds'])}s"
        )
        if r.get("declare"):
            d = r["declare"]
            lines.append(
                f"- DECLARE: cases={d['violated_case_count']}, "
                f"devs={d['deviation_total']}, time={_fmt(d['duration_seconds'])}s, "
                f"template=`{d['template']}`"
            )
            cpr = r["case_precision_recall"]
            lines.append(
                f"- Case PR (KG): P={cpr['kg']['precision']}, R={cpr['kg']['recall']}; "
                f"(DECLARE): P={cpr['declare']['precision']}, R={cpr['declare']['recall']}; "
                f"sets_equal={cpr['sets_equal']}"
            )
        else:
            epr = r["entity_precision_recall"]
            lines.append(
                f"- Entity PR: P={epr['precision']}, R={epr['recall']} "
                f"(TP={epr['true_positives']}, FP={epr['false_positives']}, FN={epr['false_negatives']})"
            )
        lines.append(f"- Complexity: {r['complexity']}")
        lines.append("- Sample injected faults:")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(r["sample_injected"], indent=2))
        lines.append("```")
        lines.append("")

    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    REPORT_JSON.write_text(
        json.dumps({"generated_at": now, "phase": "isolated", "results": results}, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {REPORT_MD}", flush=True)
    print(f"Wrote {REPORT_JSON}", flush=True)


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def run_isolated_phase() -> list[dict]:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for dataset in DATASETS:
        print(f"\n=== Isolated dataset: {dataset['name']} ===", flush=True)
        for rule in RULES:
            results.append(run_isolated_rule(dataset, rule, regenerate=True))
    write_isolated_report(results)
    summary = {
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "results": results,
    }
    (OUT_ROOT / "suite_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if summary["failed"]:
        raise SystemExit(f"Isolated phase failed: {summary['failed']} cases")
    return results


def run_combined_for_dataset(dataset: dict) -> dict:
    cfg_path = BENCH_ROOT / f"_suite_{dataset['name']}_all.ini"
    cfg_path.write_text(_benchmark_ini(dataset, None), encoding="utf-8")
    print(f"[{dataset['name']}/ALL] generating...", flush=True)
    stats = generate_benchmark(load_benchmark_config(cfg_path))
    bench_stats = json.loads(Path(stats.outputs["statistics"]).read_text(encoding="utf-8"))
    ttl = Path(stats.outputs["corrupted_knowledge_graph"])
    xes = Path(stats.outputs["corrupted_xes"])

    print(f"[{dataset['name']}/ALL] loading + validating all KG rules...", flush=True)
    load_started = time.perf_counter()
    graph = load_graph(ttl)
    load_seconds = round(time.perf_counter() - load_started, 6)
    val_dir = OUT_ROOT / f"val_all_{dataset['name']}"
    val_dir.mkdir(parents=True, exist_ok=True)
    report_path = val_dir / "validation.json"
    report = validate_knowledge_graph(
        graph,
        knowledge_graph_path=ttl,
        report_path=report_path,
        rules=VALIDATION_RULES,
    )
    val_payload = json.loads(report_path.read_text(encoding="utf-8"))

    print(f"[{dataset['name']}/ALL] DECLARE on R1–R4 templates...", flush=True)
    declare_by_rule = {}
    for rule in sorted(DECLARE_RULES):
        rid = RULE_ID[rule]
        declare_by_rule[rid] = _run_declare_cases(xes, rid)
        ddir = OUT_ROOT / f"declare_all_{dataset['name']}"
        ddir.mkdir(parents=True, exist_ok=True)
        (ddir / f"{rule}.json").write_text(
            json.dumps(declare_by_rule[rid], indent=2), encoding="utf-8"
        )

    per_rule = []
    all_ok = True
    for rule in RULES:
        rid = RULE_ID[rule]
        applied = bench_stats["applied"][rule]["applied"]
        result = next(r for r in val_payload["results"] if r["rule_id"] == rid)
        corruptions = [c for c in bench_stats["corruptions"] if c["rule_id"] == rid]
        kg_cases = _kg_cases(result.get("violations") or [])
        entry: dict = {
            "rule": rid,
            "applied": applied,
            "eligible": bench_stats["applied"][rule]["eligible"],
            "kg_rows": result["violation_count"],
            "kg_cases": sorted(kg_cases),
            "kg_case_count": len(kg_cases),
            "validation_seconds": result["duration_seconds"],
        }
        if rule in DECLARE_RULES:
            injected = _injected_cases(corruptions, rid)
            dec = declare_by_rule[rid]
            cpr_kg = _case_pr(injected, kg_cases)
            cpr_dec = _case_pr(injected, set(dec["violated_cases"]))
            entry["declare"] = dec
            entry["case_precision_recall"] = {"kg": cpr_kg, "declare": cpr_dec}
            ok = cpr_kg["recall"] == 1.0 and cpr_dec["recall"] == 1.0
            note = (
                f"KG cases={len(kg_cases)} rows={result['violation_count']}; "
                f"DECLARE cases={dec['violated_case_count']}; "
                f"case recall KG/DEC={cpr_kg['recall']}/{cpr_dec['recall']}"
            )
        else:
            epr = _entity_pr(rid, corruptions, result.get("violations") or [])
            entry["entity_precision_recall"] = epr
            ok = epr["recall"] == 1.0 and result["violation_count"] >= applied
            note = (
                f"rows={result['violation_count']} (>= {applied}); "
                f"P={epr['precision']} R={epr['recall']}"
            )
        entry["ok"] = ok
        entry["note"] = note
        all_ok = all_ok and ok
        print(f"  [{rid}] {'PASS' if ok else 'FAIL'}: {note}", flush=True)
        per_rule.append(entry)

    conversion = bench_stats.get("conversion") or {}
    return {
        "dataset": dataset["name"],
        "bench_dir": stats.run_dir,
        "traces": conversion.get("trace_count"),
        "events": conversion.get("event_count"),
        "triples": conversion.get("triple_count"),
        "conversion_seconds": conversion.get("duration_seconds"),
        "load_seconds": load_seconds,
        "validation_seconds_total": report.duration_seconds,
        "total_injected": sum(r["applied"] for r in per_rule),
        "total_kg_rows": val_payload["total_violations"],
        "ok": all_ok,
        "per_rule": per_rule,
        "validation_report": str(report_path),
    }


def extend_combined_report(combined_cases: list[dict]) -> None:
    now = _now()
    existing_md = REPORT_MD.read_text(encoding="utf-8") if REPORT_MD.is_file() else ""
    existing_json: dict = {}
    if REPORT_JSON.is_file():
        existing_json = json.loads(REPORT_JSON.read_text(encoding="utf-8"))

    marker = "## Combined all-rules benchmarks"
    if marker in existing_md:
        existing_md = existing_md.split(marker)[0].rstrip() + "\n\n"

    lines = [
        marker,
        "",
        f"Updated: `{now}`",
        "",
        "All rules injected together (same counts/seed as isolated). "
        "KG validates all rules; DECLARE is run per R1–R4 template on the corrupted XES. "
        "R1–R4 scored by **case recall**; R5–R6 by entity recall. Collateral may raise row counts.",
        "",
        f"Combined suites passed: **{sum(1 for c in combined_cases if c['ok'])}/{len(combined_cases)}**.",
        "",
        "### Overview",
        "",
        "| Dataset | Traces | Events | Triples | Conv (s) | Load (s) | Val total (s) | Injected | KG rows | Status |",
        "|---------|--------|--------|---------|----------|----------|---------------|----------|---------|--------|",
    ]
    for c in combined_cases:
        lines.append(
            f"| {c['dataset']} | {c['traces']} | {c['events']} | {c['triples']} | "
            f"{_fmt(c['conversion_seconds'])} | {_fmt(c['load_seconds'])} | "
            f"{_fmt(c['validation_seconds_total'])} | {c['total_injected']} | "
            f"{c['total_kg_rows']} | {'PASS' if c['ok'] else 'FAIL'} |"
        )

    for c in combined_cases:
        lines.extend(
            [
                "",
                f"### Combined detail: {c['dataset']}",
                "",
                f"- Benchmark: `{c['bench_dir']}`",
                "",
                "| Rule | Inj. | KG cases | KG rows | KG (s) | DECLARE cases | DECLARE (s) | Case/Entity R | OK |",
                "|------|-----:|---------:|--------:|-------:|--------------:|------------:|--------------:|----|",
            ]
        )
        for r in c["per_rule"]:
            if "declare" in r:
                dec = r["declare"]
                rec = r["case_precision_recall"]["kg"]["recall"]
                lines.append(
                    f"| {r['rule']} | {r['applied']} | {r['kg_case_count']} | {r['kg_rows']} | "
                    f"{_fmt(r['validation_seconds'])} | {dec['violated_case_count']} | "
                    f"{_fmt(dec['duration_seconds'])} | {rec} | {'Y' if r['ok'] else 'N'} |"
                )
            else:
                rec = r["entity_precision_recall"]["recall"]
                lines.append(
                    f"| {r['rule']} | {r['applied']} | n/a | {r['kg_rows']} | "
                    f"{_fmt(r['validation_seconds'])} | n/a | n/a | {rec} | "
                    f"{'Y' if r['ok'] else 'N'} |"
                )

    REPORT_MD.write_text(existing_md + "\n".join(lines) + "\n", encoding="utf-8")
    existing_json["combined"] = {"updated_at": now, "cases": combined_cases}
    existing_json["generated_at"] = existing_json.get("generated_at", now)
    REPORT_JSON.write_text(json.dumps(existing_json, indent=2), encoding="utf-8")
    print(f"Updated {REPORT_MD}", flush=True)


def run_combined_phase() -> list[dict]:
    cases = []
    for dataset in DATASETS:
        print(f"\n=== Combined dataset: {dataset['name']} ===", flush=True)
        cases.append(run_combined_for_dataset(dataset))
    extend_combined_report(cases)
    if any(not c["ok"] for c in cases):
        raise SystemExit("Combined phase had failures")
    return cases


def main() -> None:
    phase = "all"
    if len(sys.argv) > 1:
        phase = sys.argv[1].strip().lower()
    if phase not in {"isolated", "combined", "all"}:
        raise SystemExit("Usage: run_full_experiment_suite.py [isolated|combined|all]")

    BENCH_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    if phase in {"isolated", "all"}:
        run_isolated_phase()
    if phase in {"combined", "all"}:
        run_combined_phase()
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
