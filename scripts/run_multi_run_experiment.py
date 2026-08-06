"""Full-log multi-run: reuse original benches, validate N times via SPARQL.

Usage:
  python scripts/run_multi_run_experiment.py [N] [--skip-declare]

Requires a live triple store + KG_SPARQL_* (see scripts/start_triplestore.ps1).
Default N=10. Seed 42 (original benches).
Uses experiments/baseline_single_run/benchmarks (full only).
Store load + SPARQL validation are repeated for timing variance.
Pass --skip-declare to run KG (R1–R6) only and skip PM4Py DECLARE.
Outputs under experiments/multi_run_n{N}/ (also tees console to experiment.log).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import experiment_logging as elog
import run_full_experiment_suite as suite
from src.validate_kg import validate_ttl
from src.validation_rules import VALIDATION_RULES

BASELINE_BENCH = ROOT / "experiments" / "baseline_single_run" / "benchmarks"
SEED_NOTE = 42


def _now() -> str:
    return elog.utc_now()


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _avg_metric(runs: list[dict], getter) -> float | None:
    vals = []
    for run in runs:
        value = getter(run)
        if value is not None:
            vals.append(float(value))
    return _mean(vals) if vals else None


def _fmt_count(value) -> str:
    """Format counts: whole numbers without decimals, else 4 digits."""
    if value is None:
        return "n/a"
    if isinstance(value, float) and abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return _fmt(value, 4)


def _fmt_recall(value) -> str:
    if value is None:
        return "n/a"
    if abs(float(value) - round(float(value), 1)) < 1e-9:
        return f"{round(float(value), 1)}"
    return _fmt(value)


def _bench_paths(rule: str) -> tuple[Path, Path, Path, dict]:
    name = f"bench_{rule}_full" if rule != "all" else "bench_all_full"
    bench_dir = BASELINE_BENCH / name
    stats = json.loads((bench_dir / "statistics.json").read_text(encoding="utf-8"))
    # statistics.json may still point at old benchmarks/ paths; resolve by filename.
    ttl = bench_dir / Path(stats["outputs"]["corrupted_knowledge_graph"]).name
    xes = bench_dir / Path(stats["outputs"]["corrupted_xes"]).name
    if not ttl.is_file():
        raise FileNotFoundError(ttl)
    if not xes.is_file():
        raise FileNotFoundError(xes)
    return bench_dir, ttl, xes, stats


def _validate_isolated_from_baseline(
    out_root: Path, *, run_idx: int, skip_declare: bool
) -> list[dict]:
    results = []
    for rule in suite.RULES:
        rule_id = suite.RULE_ID[rule]
        bench_dir, ttl, xes, stats = _bench_paths(rule)
        applied = stats["applied"][rule]["applied"]
        corruptions = [c for c in stats["corruptions"] if c["rule_id"] == rule_id]
        conversion = stats.get("conversion") or {}

        val_dir = out_root / f"val_{rule}_full"
        elog.log(f"  [run_{run_idx:02d}/{rule_id}] KG validating ({ttl.name})...")
        t0 = time.perf_counter()
        kg_payload, load_seconds, _ = suite._validate_kg_rule(ttl, rule_id, val_dir)
        kg_wall = time.perf_counter() - t0
        kg_result = kg_payload["results"][0]
        kg_rows = kg_result["violation_count"]
        kg_case_set = suite._kg_cases(kg_result.get("violations") or [])
        elog.log(
            f"  [run_{run_idx:02d}/{rule_id}] KG done: load={load_seconds:.3f}s "
            f"query={kg_result['duration_seconds']:.3f}s wall={kg_wall:.3f}s "
            f"rows={kg_rows}"
        )

        declare_info = None
        case_pr = None
        entity_pr = None
        if rule in suite.DECLARE_RULES:
            injected = suite._injected_cases(corruptions, rule_id)
            case_pr_kg = suite._case_pr(injected, kg_case_set)
            ok_kg, note_kg = suite._verify_isolated(
                rule_id, applied, kg_rows, case_pr_kg, None
            )
            if skip_declare:
                case_pr = {"kg": case_pr_kg}
                ok = ok_kg
                note = f"KG[{note_kg}] (DECLARE skipped)"
            else:
                elog.log(f"  [run_{run_idx:02d}/{rule_id}] DECLARE validating...")
                t1 = time.perf_counter()
                declare_info = suite._run_declare_cases(xes, rule_id)
                elog.log(
                    f"  [run_{run_idx:02d}/{rule_id}] DECLARE done: "
                    f"{declare_info['duration_seconds']:.3f}s "
                    f"(wall={time.perf_counter() - t1:.3f}s)"
                )
                ddir = out_root / f"declare_{rule}_full"
                ddir.mkdir(parents=True, exist_ok=True)
                (ddir / "declare.json").write_text(
                    json.dumps(declare_info, indent=2), encoding="utf-8"
                )
                case_pr_dec = suite._case_pr(
                    injected, set(declare_info["violated_cases"])
                )
                case_pr = {
                    "kg": case_pr_kg,
                    "declare": case_pr_dec,
                    "sets_equal": kg_case_set == set(declare_info["violated_cases"]),
                }
                ok_dec = (
                    case_pr_dec["false_negatives"] == 0 and case_pr_dec["recall"] == 1.0
                )
                ok = ok_kg and ok_dec and case_pr["sets_equal"]
                note = (
                    f"KG[{note_kg}]; DECLARE cases={declare_info['violated_case_count']}; "
                    f"sets_equal={case_pr['sets_equal']}"
                )
        else:
            entity_pr = suite._entity_pr(
                rule_id, corruptions, kg_result.get("violations") or []
            )
            ok, note = suite._verify_isolated(rule_id, applied, kg_rows, None, entity_pr)

        status = "PASS" if ok else "FAIL"
        elog.log(
            f"  [run_{run_idx:02d}/{rule_id}] {status}: rows={kg_rows} "
            f"load={load_seconds:.3f}s kg={kg_result['duration_seconds']:.3f}s ({note})"
        )
        entry = {
            "rule": rule_id,
            "ok": ok,
            "status": status,
            "applied": applied,
            "traces": conversion.get("trace_count"),
            "events": conversion.get("event_count"),
            "triples": conversion.get("triple_count"),
            "conversion_seconds": conversion.get("duration_seconds"),
            "load_seconds": load_seconds,
            "kg_val_seconds": kg_result["duration_seconds"],
            "kg_rows": kg_rows,
            "kg_cases": len(kg_case_set),
            "declare_seconds": (declare_info or {}).get("duration_seconds"),
            "declare_cases": (declare_info or {}).get("violated_case_count"),
        }
        if case_pr:
            entry["kg_precision"] = case_pr["kg"]["precision"]
            entry["kg_recall"] = case_pr["kg"]["recall"]
            if "declare" in case_pr:
                entry["declare_precision"] = case_pr["declare"]["precision"]
                entry["declare_recall"] = case_pr["declare"]["recall"]
                entry["sets_equal"] = case_pr["sets_equal"]
        if entity_pr:
            entry["entity_precision"] = entity_pr["precision"]
            entry["entity_recall"] = entity_pr["recall"]
        results.append(entry)
    return results


def _validate_combined_from_baseline(
    out_root: Path, *, run_idx: int, skip_declare: bool
) -> dict:
    bench_dir, ttl, xes, stats = _bench_paths("all")

    elog.log(f"  [run_{run_idx:02d}/ALL] loading + validating all KG rules...")
    val_dir = out_root / "val_all_full"
    val_dir.mkdir(parents=True, exist_ok=True)
    report_path = val_dir / "validation.json"
    t0 = time.perf_counter()
    report, load_seconds = validate_ttl(
        ttl,
        report_path=report_path,
        rules=VALIDATION_RULES,
    )
    kg_wall = time.perf_counter() - t0
    val_payload = json.loads(report_path.read_text(encoding="utf-8"))
    elog.log(
        f"  [run_{run_idx:02d}/ALL] KG done: load={load_seconds:.3f}s "
        f"val_total={report.duration_seconds:.3f}s wall={kg_wall:.3f}s "
        f"violations={val_payload['total_violations']}"
    )

    declare_by_rule: dict = {}
    if skip_declare:
        elog.log(f"  [run_{run_idx:02d}/ALL] DECLARE skipped")
    else:
        elog.log(f"  [run_{run_idx:02d}/ALL] DECLARE on R1-R4...")
        for rule in sorted(suite.DECLARE_RULES):
            rid = suite.RULE_ID[rule]
            t1 = time.perf_counter()
            declare_by_rule[rid] = suite._run_declare_cases(xes, rid)
            elog.log(
                f"  [run_{run_idx:02d}/ALL/{rid}] DECLARE "
                f"{declare_by_rule[rid]['duration_seconds']:.3f}s "
                f"(wall={time.perf_counter() - t1:.3f}s)"
            )
            ddir = out_root / "declare_all_full"
            ddir.mkdir(parents=True, exist_ok=True)
            (ddir / f"{rule}.json").write_text(
                json.dumps(declare_by_rule[rid], indent=2), encoding="utf-8"
            )

    per_rule = []
    all_ok = True
    for rule in suite.RULES:
        rid = suite.RULE_ID[rule]
        applied = stats["applied"][rule]["applied"]
        result = next(r for r in val_payload["results"] if r["rule_id"] == rid)
        corruptions = [c for c in stats["corruptions"] if c["rule_id"] == rid]
        kg_cases = suite._kg_cases(result.get("violations") or [])
        entry: dict = {
            "rule": rid,
            "applied": applied,
            "kg_rows": result["violation_count"],
            "kg_cases": len(kg_cases),
            "kg_val_seconds": result["duration_seconds"],
        }
        if rule in suite.DECLARE_RULES:
            injected = suite._injected_cases(corruptions, rid)
            cpr_kg = suite._case_pr(injected, kg_cases)
            entry["kg_precision"] = cpr_kg["precision"]
            entry["kg_recall"] = cpr_kg["recall"]
            if skip_declare:
                ok = cpr_kg["recall"] == 1.0
                note = f"KG cases={len(kg_cases)}; R={cpr_kg['recall']} (DECLARE skipped)"
            else:
                dec = declare_by_rule[rid]
                cpr_dec = suite._case_pr(injected, set(dec["violated_cases"]))
                entry["declare_cases"] = dec["violated_case_count"]
                entry["declare_seconds"] = dec["duration_seconds"]
                entry["declare_precision"] = cpr_dec["precision"]
                entry["declare_recall"] = cpr_dec["recall"]
                ok = cpr_kg["recall"] == 1.0 and cpr_dec["recall"] == 1.0
                note = (
                    f"KG cases={len(kg_cases)}; DECLARE={dec['violated_case_count']}; "
                    f"R={cpr_kg['recall']}/{cpr_dec['recall']}"
                )
        else:
            epr = suite._entity_pr(rid, corruptions, result.get("violations") or [])
            entry["entity_precision"] = epr["precision"]
            entry["entity_recall"] = epr["recall"]
            ok = epr["recall"] == 1.0 and result["violation_count"] >= applied
            note = f"rows={result['violation_count']} P={epr['precision']} R={epr['recall']}"
        entry["ok"] = ok
        all_ok = all_ok and ok
        elog.log(
            f"  [run_{run_idx:02d}/{rid}] {'PASS' if ok else 'FAIL'}: {note}"
        )
        per_rule.append(entry)

    conversion = stats.get("conversion") or {}
    return {
        "ok": all_ok,
        "traces": conversion.get("trace_count"),
        "events": conversion.get("event_count"),
        "triples": conversion.get("triple_count"),
        "conversion_seconds": conversion.get("duration_seconds"),
        "load_seconds": load_seconds,
        "validation_seconds_total": report.duration_seconds,
        "total_injected": sum(r["applied"] for r in per_rule),
        "total_kg_rows": val_payload["total_violations"],
        "per_rule": per_rule,
    }


def _run_validation_repeat(
    exp_root: Path, run_idx: int, n_runs: int, *, skip_declare: bool
) -> dict:
    run_name = f"run_{run_idx:02d}"
    run_dir = exp_root / run_name
    out_root = run_dir / "validation"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    elog.log("=" * 60)
    elog.log(f"=== Validation repeat {run_idx}/{n_runs} ({run_name}) ===")
    elog.log("=" * 60)
    started = time.perf_counter()

    elog.log(f"--- {run_name}: isolated ---")
    isolated = _validate_isolated_from_baseline(
        out_root, run_idx=run_idx, skip_declare=skip_declare
    )
    elog.log(f"--- {run_name}: combined ---")
    combined = _validate_combined_from_baseline(
        out_root, run_idx=run_idx, skip_declare=skip_declare
    )

    elapsed = round(time.perf_counter() - started, 3)
    payload = {
        "run": run_idx,
        "run_name": run_name,
        "finished_at": _now(),
        "wall_seconds": elapsed,
        "ok": all(r["ok"] for r in isolated) and combined["ok"],
        "isolated": isolated,
        "combined": combined,
    }
    (run_dir / "run_summary.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    elog.log(f"[{run_name}] finished in {elapsed}s ok={payload['ok']}")
    return payload


def write_aggregate_report(
    runs: list[dict],
    n_runs: int,
    benches: dict,
    exp_root: Path,
    *,
    skip_declare: bool = False,
) -> None:
    lines: list[str] = []
    lines.append("# Multi-run experiment report (full log)")
    lines.append("")
    lines.append(f"- Generated: `{_now()}`")
    lines.append(f"- Seed: `{SEED_NOTE}` (original benches)")
    lines.append(f"- Runs: `{n_runs}`")
    lines.append("- KG validation: **SPARQL** on configured triple store")
    lines.append("- Mode: **reuse original benches**; validate ×N")
    lines.append(
        f"- DECLARE: `{'skipped' if skip_declare else 'included (R1–R4)'}`"
    )
    lines.append(f"- Benchmarks: `{BASELINE_BENCH}`")
    lines.append(f"- Output: `{exp_root}`")
    lines.append("")
    lines.append("## Shared benchmarks (from original experiment)")
    lines.append("")
    lines.append("| Rule | Applied | Traces | Events | Triples | Conversion (s) |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for row in benches["isolated"]:
        lines.append(
            f"| {row['rule']} | {row['applied']} | {row['traces']} | {row['events']} | "
            f"{row['triples']} | {_fmt(row['conversion_seconds'], 3)} |"
        )
    c = benches["combined"]
    lines.append(
        f"| ALL | — | {c['traces']} | {c['events']} | {c['triples']} | "
        f"{_fmt(c['conversion_seconds'], 3)} |"
    )
    lines.append("")

    lines.append("## Run overview")
    lines.append("")
    lines.append("| Run | OK | Wall (s) |")
    lines.append("|---:|---|---:|")
    for r in runs:
        lines.append(
            f"| {r['run']} | {'PASS' if r['ok'] else 'FAIL'} | {_fmt(r['wall_seconds'], 3)} |"
        )
    walls = [float(r["wall_seconds"]) for r in runs]
    lines.append(
        f"| **agg** | — | mean={_fmt(_mean(walls), 3)} min={_fmt(min(walls), 3)} "
        f"max={_fmt(max(walls), 3)} |"
    )
    lines.append("")

    # Original-style summary tables using averages across validation repeats.
    lines.append("## Isolated per-rule summary (averages)")
    lines.append("")
    n_pass_iso = sum(
        1
        for rule in [suite.RULE_ID[r] for r in suite.RULES]
        if all(
            next(x for x in run["isolated"] if x["rule"] == rule)["ok"] for run in runs
        )
    )
    n_iso = len(suite.RULES)
    lines.append(
        f"Averaged over **{n_runs}** validation repeats on the original full benches. "
        f"Passed **{n_pass_iso}/{n_iso}** rules across all repeats."
    )
    lines.append("")
    lines.append(
        "| Dataset | Rule | Traces | Events | Triples | Conv (s) | Load (s) | KG val (s) | "
        "Inj. | KG cases | KG rows | DECLARE cases | DECLARE (s) | Case P | Case R | Status |"
    )
    lines.append(
        "|---------|------|--------|--------|---------|----------|----------|------------|"
        "------|----------|---------|---------------|-------------|--------|--------|--------|"
    )
    for meta in benches["isolated"]:
        rule = meta["rule"]
        is_declare = rule in {"R1", "R2", "R3", "R4"}
        load = _avg_metric(
            runs, lambda run, rid=rule: next(x for x in run["isolated"] if x["rule"] == rid)["load_seconds"]
        )
        kg_val = _avg_metric(
            runs,
            lambda run, rid=rule: next(x for x in run["isolated"] if x["rule"] == rid)[
                "kg_val_seconds"
            ],
        )
        kg_rows = _avg_metric(
            runs,
            lambda run, rid=rule: next(x for x in run["isolated"] if x["rule"] == rid)["kg_rows"],
        )
        if is_declare:
            kg_cases = _avg_metric(
                runs,
                lambda run, rid=rule: next(x for x in run["isolated"] if x["rule"] == rid)[
                    "kg_cases"
                ],
            )
            dec_cases = _avg_metric(
                runs,
                lambda run, rid=rule: next(x for x in run["isolated"] if x["rule"] == rid).get(
                    "declare_cases"
                ),
            )
            dec_s = _avg_metric(
                runs,
                lambda run, rid=rule: next(x for x in run["isolated"] if x["rule"] == rid).get(
                    "declare_seconds"
                ),
            )
            case_p = _avg_metric(
                runs,
                lambda run, rid=rule: next(x for x in run["isolated"] if x["rule"] == rid).get(
                    "kg_precision"
                ),
            )
            case_r = _avg_metric(
                runs,
                lambda run, rid=rule: next(x for x in run["isolated"] if x["rule"] == rid).get(
                    "kg_recall"
                ),
            )
            kg_cases_s = _fmt_count(kg_cases)
            dec_cases_s = _fmt_count(dec_cases)
            dec_s_s = _fmt(dec_s)
        else:
            kg_cases_s = "n/a"
            dec_cases_s = "n/a"
            dec_s_s = "n/a"
            case_p = _avg_metric(
                runs,
                lambda run, rid=rule: next(x for x in run["isolated"] if x["rule"] == rid).get(
                    "entity_precision"
                ),
            )
            case_r = _avg_metric(
                runs,
                lambda run, rid=rule: next(x for x in run["isolated"] if x["rule"] == rid).get(
                    "entity_recall"
                ),
            )
        ok_all = all(
            next(x for x in run["isolated"] if x["rule"] == rule)["ok"] for run in runs
        )
        lines.append(
            f"| full | {rule} | {meta['traces']} | {meta['events']} | {meta['triples']} | "
            f"{_fmt(meta['conversion_seconds'])} | {_fmt(load)} | {_fmt(kg_val)} | "
            f"{meta['applied']} | {kg_cases_s} | {_fmt_count(kg_rows)} | {dec_cases_s} | "
            f"{dec_s_s} | {_fmt(case_p)} | {_fmt(case_r)} | {'PASS' if ok_all else 'FAIL'} |"
        )
    lines.append("")
    lines.extend(
        [
            "### Notes on counting",
            "",
            "- **Primary ground truth for R1–R4:** violated **cases** (injected `trace_id`).",
            "- KG may emit more **rows** than cases (e.g. R2 multiple approvals, R4 both succession halves).",
            "- DECLARE is scored on unfit cases for the single template of that rule.",
            "- R5–R6 use entity-level precision/recall (no DECLARE).",
            "- Timing columns (Load / KG val / DECLARE) are **means** over the validation repeats; "
            "size/conversion come from the shared original benches.",
            "",
        ]
    )

    lines.append("## Combined all-rules benchmarks (averages)")
    lines.append("")
    lines.append(
        "All rules injected together (same original `bench_all_full`). "
        "Values below are averages over the validation repeats."
    )
    lines.append("")
    comb_ok = all(r["combined"]["ok"] for r in runs)
    lines.append(
        f"Combined suites passed: **{1 if comb_ok else 0}/1** "
        f"(across all {n_runs} repeats)."
    )
    lines.append("")
    lines.append("### Overview")
    lines.append("")
    lines.append(
        "| Dataset | Traces | Events | Triples | Conv (s) | Load (s) | Val total (s) | "
        "Injected | KG rows | Status |"
    )
    lines.append(
        "|---------|--------|--------|---------|----------|----------|---------------|"
        "----------|---------|--------|"
    )
    cmeta = benches["combined"]
    load_c = _avg_metric(runs, lambda run: run["combined"]["load_seconds"])
    val_c = _avg_metric(runs, lambda run: run["combined"]["validation_seconds_total"])
    rows_c = _avg_metric(runs, lambda run: run["combined"]["total_kg_rows"])
    inj_c = _avg_metric(runs, lambda run: run["combined"]["total_injected"])
    lines.append(
        f"| full | {cmeta['traces']} | {cmeta['events']} | {cmeta['triples']} | "
        f"{_fmt(cmeta['conversion_seconds'])} | {_fmt(load_c)} | {_fmt(val_c)} | "
        f"{_fmt_count(inj_c)} | {_fmt_count(rows_c)} | {'PASS' if comb_ok else 'FAIL'} |"
    )
    lines.append("")
    lines.append("### Combined detail: full")
    lines.append("")
    lines.append(f"- Benchmark: `{cmeta['bench_dir']}`")
    lines.append(f"- Values: **averages** over `{n_runs}` validation repeats")
    lines.append("")
    lines.append(
        "| Rule | Inj. | KG cases | KG rows | KG (s) | DECLARE cases | DECLARE (s) | "
        "Case/Entity R | OK |"
    )
    lines.append(
        "|------|-----:|---------:|--------:|-------:|--------------:|------------:|"
        "--------------:|----|"
    )
    for rule in [suite.RULE_ID[r] for r in suite.RULES]:
        is_declare = rule in {"R1", "R2", "R3", "R4"}
        applied = next(
            x["applied"]
            for x in runs[0]["combined"]["per_rule"]
            if x["rule"] == rule
        )
        kg_rows = _avg_metric(
            runs,
            lambda run, rid=rule: next(
                x for x in run["combined"]["per_rule"] if x["rule"] == rid
            )["kg_rows"],
        )
        kg_s = _avg_metric(
            runs,
            lambda run, rid=rule: next(
                x for x in run["combined"]["per_rule"] if x["rule"] == rid
            )["kg_val_seconds"],
        )
        ok_all = all(
            next(x for x in run["combined"]["per_rule"] if x["rule"] == rule)["ok"]
            for run in runs
        )
        if is_declare:
            kg_cases = _avg_metric(
                runs,
                lambda run, rid=rule: next(
                    x for x in run["combined"]["per_rule"] if x["rule"] == rid
                )["kg_cases"],
            )
            dec_cases = _avg_metric(
                runs,
                lambda run, rid=rule: next(
                    x for x in run["combined"]["per_rule"] if x["rule"] == rid
                ).get("declare_cases"),
            )
            dec_s = _avg_metric(
                runs,
                lambda run, rid=rule: next(
                    x for x in run["combined"]["per_rule"] if x["rule"] == rid
                ).get("declare_seconds"),
            )
            recall = _avg_metric(
                runs,
                lambda run, rid=rule: next(
                    x for x in run["combined"]["per_rule"] if x["rule"] == rid
                ).get("kg_recall"),
            )
            lines.append(
                f"| {rule} | {applied} | {_fmt_count(kg_cases)} | {_fmt_count(kg_rows)} | "
                f"{_fmt(kg_s)} | {_fmt_count(dec_cases)} | {_fmt(dec_s)} | "
                f"{_fmt_recall(recall)} | {'Y' if ok_all else 'N'} |"
            )
        else:
            recall = _avg_metric(
                runs,
                lambda run, rid=rule: next(
                    x for x in run["combined"]["per_rule"] if x["rule"] == rid
                ).get("entity_recall"),
            )
            lines.append(
                f"| {rule} | {applied} | n/a | {_fmt_count(kg_rows)} | {_fmt(kg_s)} | "
                f"n/a | n/a | {_fmt_recall(recall)} | {'Y' if ok_all else 'N'} |"
            )
    lines.append("")

    for r in runs:
        lines.append(f"## Run {r['run']:02d}")
        lines.append("")
        lines.append(
            f"- Finished: `{r['finished_at']}` | Wall: `{_fmt(r['wall_seconds'], 3)}s` | "
            f"OK: `{'PASS' if r['ok'] else 'FAIL'}`"
        )
        lines.append("")
        lines.append("### Isolated")
        lines.append("")
        lines.append(
            "| Rule | Status | Applied | Load (s) | KG val (s) | DECLARE (s) | "
            "KG cases | Decl cases | KG P/R | Decl P/R | Ent P/R |"
        )
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|---|---|")
        for row in r["isolated"]:
            kg_pr = (
                f"{_fmt(row.get('kg_precision'))}/{_fmt(row.get('kg_recall'))}"
                if row.get("kg_precision") is not None
                else "—"
            )
            d_pr = (
                f"{_fmt(row.get('declare_precision'))}/{_fmt(row.get('declare_recall'))}"
                if row.get("declare_precision") is not None
                else "—"
            )
            e_pr = (
                f"{_fmt(row.get('entity_precision'))}/{_fmt(row.get('entity_recall'))}"
                if row.get("entity_precision") is not None
                else "—"
            )
            lines.append(
                f"| {row['rule']} | {row['status']} | {row['applied']} | "
                f"{_fmt(row['load_seconds'], 3)} | {_fmt(row['kg_val_seconds'], 3)} | "
                f"{_fmt(row.get('declare_seconds'), 3)} | {row['kg_cases']} | "
                f"{row.get('declare_cases', '—')} | {kg_pr} | {d_pr} | {e_pr} |"
            )
        lines.append("")
        lines.append("### Combined")
        lines.append("")
        lines.append(
            f"- Load: `{_fmt(r['combined']['load_seconds'], 3)}s` | "
            f"KG total: `{_fmt(r['combined']['validation_seconds_total'], 3)}s` | "
            f"Injected: `{r['combined']['total_injected']}` | "
            f"KG rows: `{r['combined']['total_kg_rows']}`"
        )
        lines.append("")
        lines.append(
            "| Rule | OK | Applied | KG rows | KG cases | Decl cases | "
            "KG val (s) | Decl (s) | KG P/R | Decl P/R | Ent P/R |"
        )
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|---|---|")
        for row in r["combined"]["per_rule"]:
            kg_pr = (
                f"{_fmt(row.get('kg_precision'))}/{_fmt(row.get('kg_recall'))}"
                if row.get("kg_precision") is not None
                else "—"
            )
            d_pr = (
                f"{_fmt(row.get('declare_precision'))}/{_fmt(row.get('declare_recall'))}"
                if row.get("declare_precision") is not None
                else "—"
            )
            e_pr = (
                f"{_fmt(row.get('entity_precision'))}/{_fmt(row.get('entity_recall'))}"
                if row.get("entity_precision") is not None
                else "—"
            )
            lines.append(
                f"| {row['rule']} | {'PASS' if row['ok'] else 'FAIL'} | {row['applied']} | "
                f"{row['kg_rows']} | {row['kg_cases']} | {row.get('declare_cases', '—')} | "
                f"{_fmt(row['kg_val_seconds'], 3)} | {_fmt(row.get('declare_seconds'), 3)} | "
                f"{kg_pr} | {d_pr} | {e_pr} |"
            )
        lines.append("")

    lines.append("## Aggregate (mean / min / max over validation repeats)")
    lines.append("")
    lines.append("### Isolated timings & metrics")
    lines.append("")
    lines.append(
        "| Rule | Metric | Mean | Min | Max |"
    )
    lines.append("|---|---|---:|---:|---:|")
    metrics = [
        "load_seconds",
        "kg_val_seconds",
        "declare_seconds",
        "kg_rows",
        "kg_cases",
        "declare_cases",
        "kg_precision",
        "kg_recall",
        "declare_precision",
        "declare_recall",
        "entity_precision",
        "entity_recall",
    ]
    for rule in [suite.RULE_ID[r] for r in suite.RULES]:
        for metric in metrics:
            vals = []
            for run in runs:
                row = next(x for x in run["isolated"] if x["rule"] == rule)
                if row.get(metric) is not None:
                    vals.append(float(row[metric]))
            if not vals:
                continue
            lines.append(
                f"| {rule} | {metric} | {_fmt(_mean(vals), 4)} | "
                f"{_fmt(min(vals), 4)} | {_fmt(max(vals), 4)} |"
            )
    lines.append("")
    lines.append("### Combined timings & metrics")
    lines.append("")
    lines.append("| Scope | Metric | Mean | Min | Max |")
    lines.append("|---|---|---:|---:|---:|")
    for metric in ("load_seconds", "validation_seconds_total", "total_kg_rows"):
        vals = [float(r["combined"][metric]) for r in runs]
        lines.append(
            f"| ALL | {metric} | {_fmt(_mean(vals), 4)} | "
            f"{_fmt(min(vals), 4)} | {_fmt(max(vals), 4)} |"
        )
    for rule in [suite.RULE_ID[r] for r in suite.RULES]:
        for metric in (
            "kg_val_seconds",
            "declare_seconds",
            "kg_rows",
            "kg_cases",
            "declare_cases",
            "kg_precision",
            "kg_recall",
            "declare_precision",
            "declare_recall",
            "entity_precision",
            "entity_recall",
        ):
            vals = []
            for run in runs:
                row = next(x for x in run["combined"]["per_rule"] if x["rule"] == rule)
                if row.get(metric) is not None:
                    vals.append(float(row[metric]))
            if not vals:
                continue
            lines.append(
                f"| {rule} | {metric} | {_fmt(_mean(vals), 4)} | "
                f"{_fmt(min(vals), 4)} | {_fmt(max(vals), 4)} |"
            )
    lines.append("")

    report_md = exp_root / "experiment_report.md"
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report_json = {
        "generated_at": _now(),
        "seed": SEED_NOTE,
        "n_runs": n_runs,
        "mode": "reuse_original_benches_validate_xn",
        "validation_engine": "sparql",
        "skip_declare": skip_declare,
        "benchmarks_source": str(BASELINE_BENCH),
        "benches": benches,
        "runs": runs,
    }
    (exp_root / "experiment_report.json").write_text(
        json.dumps(report_json, indent=2), encoding="utf-8"
    )
    elog.log(f"Wrote {report_md}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reuse original full benches; validate R1–R6 via SPARQL ×N."
    )
    parser.add_argument(
        "n_runs",
        nargs="?",
        type=int,
        default=10,
        help="Number of validation repeats (default: 10)",
    )
    parser.add_argument(
        "--skip-declare",
        action="store_true",
        help="Skip PM4Py DECLARE; run KG SPARQL validation only (R1–R6)",
    )
    args = parser.parse_args()
    n_runs = args.n_runs
    skip_declare = args.skip_declare
    exp_root = ROOT / "experiments" / f"multi_run_n{n_runs}"

    if exp_root.exists():
        shutil.rmtree(exp_root)
    exp_root.mkdir(parents=True, exist_ok=True)

    tee = elog.TeeStdout(exp_root / "experiment.log")
    sys.stdout = tee  # type: ignore[assignment]
    try:
        _main_impl(n_runs, exp_root, skip_declare=skip_declare)
    finally:
        sys.stdout = tee._out  # type: ignore[attr-defined]
        tee.close()


def _main_impl(n_runs: int, exp_root: Path, *, skip_declare: bool) -> None:
    for rule in list(suite.RULES) + ["all"]:
        name = f"bench_{rule}_full" if rule != "all" else "bench_all_full"
        if not (BASELINE_BENCH / name / "statistics.json").is_file():
            raise SystemExit(f"Missing baseline benchmark: {BASELINE_BENCH / name}")

    elog.log(f"Using original experiment benches from: {BASELINE_BENCH}")
    elog.log("KG validation: SPARQL triple store")
    elog.log(
        f"Mode: reuse benches + validate x{n_runs}"
        f"{' (DECLARE skipped)' if skip_declare else ''}"
    )
    elog.log(f"Output: {exp_root}")
    elog.log(f"Live log file: {exp_root / 'experiment.log'}")
    elog.preflight_sparql(label="multi-run experiment")

    benches_meta = {
        "generated_at": _now(),
        "seed": SEED_NOTE,
        "dataset": "full",
        "source": str(BASELINE_BENCH),
        "validation_engine": "sparql",
        "skip_declare": skip_declare,
        "isolated": [],
        "combined": {},
    }
    for rule in suite.RULES:
        bench_dir, _ttl, _xes, stats = _bench_paths(rule)
        conversion = stats.get("conversion") or {}
        benches_meta["isolated"].append(
            {
                "rule": suite.RULE_ID[rule],
                "applied": stats["applied"][rule]["applied"],
                "traces": conversion.get("trace_count"),
                "events": conversion.get("event_count"),
                "triples": conversion.get("triple_count"),
                "conversion_seconds": conversion.get("duration_seconds"),
                "bench_dir": str(bench_dir),
            }
        )
    bench_dir, _ttl, _xes, stats = _bench_paths("all")
    conversion = stats.get("conversion") or {}
    benches_meta["combined"] = {
        "traces": conversion.get("trace_count"),
        "events": conversion.get("event_count"),
        "triples": conversion.get("triple_count"),
        "conversion_seconds": conversion.get("duration_seconds"),
        "bench_dir": str(bench_dir),
    }
    (exp_root / "benchmarks_meta.json").write_text(
        json.dumps(benches_meta, indent=2), encoding="utf-8"
    )

    runs: list[dict] = []
    experiment_started = time.perf_counter()
    for i in range(1, n_runs + 1):
        runs.append(
            _run_validation_repeat(
                exp_root, i, n_runs, skip_declare=skip_declare
            )
        )
        write_aggregate_report(
            runs, n_runs, benches_meta, exp_root, skip_declare=skip_declare
        )
        elapsed = time.perf_counter() - experiment_started
        mean_wall = elapsed / len(runs)
        remaining = n_runs - len(runs)
        eta = mean_wall * remaining
        elog.log(
            f"Progress {len(runs)}/{n_runs} | last_wall={runs[-1]['wall_seconds']:.1f}s | "
            f"mean_so_far={mean_wall:.1f}s | elapsed={elog.fmt_eta(elapsed)} | "
            f"ETA ~{elog.fmt_eta(eta)}"
        )

    write_aggregate_report(
        runs, n_runs, benches_meta, exp_root, skip_declare=skip_declare
    )
    failed = sum(1 for r in runs if not r["ok"])
    total = time.perf_counter() - experiment_started
    if failed:
        raise SystemExit(
            f"Multi-run finished with {failed} failed run(s) "
            f"in {elog.fmt_eta(total)}"
        )
    elog.log(f"Multi-run experiment Done in {elog.fmt_eta(total)}.")


if __name__ == "__main__":
    main()
