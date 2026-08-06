"""Compare KG validation (R1–R4) with PM4Py DECLARE on 10-declaration benches."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import experiment_logging as elog
from src.validate_declare_baseline import (
    declare_model_for_rule,
    load_xes,
    result_to_dict,
    run_declare_conformance,
)
from src.validate_kg import validate_ttl
from src.validation_rules import DECLARE_MODEL_R1_R4, VALIDATION_RULES

BENCH_ROOT = ROOT / "experiments" / "baseline_single_run" / "benchmarks"
OUT_ROOT = ROOT / "output" / "declare_baseline_comparison"
CLEAN_XES = ROOT / "dataset" / "DomesticDeclarations.sample_10declarations.xes"
RULES = ("R1", "R2", "R3", "R4")


def _rule_obj(rule_id: str):
    for rule in VALIDATION_RULES:
        if rule.rule_id == rule_id:
            return rule
    raise KeyError(rule_id)


def _bench_dir(rule_id: str) -> Path:
    return BENCH_ROOT / f"bench_{rule_id.lower()}_10declarations"


def _resolve_bench_outputs(bench: Path, stats: dict) -> tuple[Path, Path]:
    """Resolve XES/TTL by filename (statistics.json may still point at old paths)."""
    xes = bench / Path(stats["outputs"]["corrupted_xes"]).name
    ttl = bench / Path(stats["outputs"]["corrupted_knowledge_graph"]).name
    if not xes.is_file():
        raise FileNotFoundError(xes)
    if not ttl.is_file():
        raise FileNotFoundError(ttl)
    return xes, ttl


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rerun_kg(rule_id: str, ttl_path: Path, report_path: Path) -> dict:
    started = time.perf_counter()
    report, load_seconds = validate_ttl(
        ttl_path,
        report_path=report_path,
        rules=(_rule_obj(rule_id),),
    )
    wall = round(time.perf_counter() - started, 6)
    row = report.results[0]
    return {
        "status": row.status,
        "violation_count": row.violation_count,
        "duration_seconds": row.duration_seconds,
        "load_seconds": load_seconds,
        "wall_seconds": wall,
        "engine": "sparql",
        "knowledge_graph": str(ttl_path),
        "report_path": str(report_path),
    }


def run_rule_comparison(rule_id: str) -> dict:
    bench = _bench_dir(rule_id)
    stats = _load_json(bench / "statistics.json")
    xes_path, ttl_path = _resolve_bench_outputs(bench, stats)
    injected = stats.get("applied", {}).get(rule_id.lower(), {}).get("applied", 0)

    elog.log(f"Comparing {rule_id}: DECLARE on {xes_path.name}...")
    t0 = time.perf_counter()
    log = load_xes(xes_path)
    declare_res = run_declare_conformance(log, declare_model_for_rule(rule_id))
    elog.log(
        f"  {rule_id} DECLARE done in {time.perf_counter() - t0:.3f}s "
        f"(devs={declare_res.violation_count})"
    )

    elog.log(f"  {rule_id} KG SPARQL on {ttl_path.name}...")
    t1 = time.perf_counter()
    kg = _rerun_kg(rule_id, ttl_path, OUT_ROOT / f"kg_rerun_{rule_id.lower()}" / "validation.json")
    elog.log(
        f"  {rule_id} KG done in {time.perf_counter() - t1:.3f}s "
        f"(load={kg['load_seconds']:.3f}s query={kg['duration_seconds']:.3f}s "
        f"rows={kg['violation_count']})"
    )

    return {
        "rule_id": rule_id,
        "benchmark": str(bench),
        "injected_count": injected,
        "declare": result_to_dict(declare_res),
        "kg": kg,
    }


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    tee = elog.TeeStdout(OUT_ROOT / "experiment.log")
    sys.stdout = tee  # type: ignore[assignment]
    try:
        elog.log(f"DECLARE vs KG comparison; benches={BENCH_ROOT}")
        elog.preflight_sparql(label="declare baseline comparison")

        # Sanity: clean log should fit the DECLARE model.
        clean = load_xes(CLEAN_XES)
        clean_declare = run_declare_conformance(clean, DECLARE_MODEL_R1_R4)
        elog.log(
            f"Clean log DECLARE status={clean_declare.status} "
            f"devs={clean_declare.violation_count}"
        )

        per_rule = []
        for rule_id in RULES:
            per_rule.append(run_rule_comparison(rule_id))

        summary = []
        for row in per_rule:
            summary.append(
                {
                    "rule": row["rule_id"],
                    "injected": row["injected_count"],
                    "kg_detected": row["kg"]["violation_count"],
                    "kg_s": row["kg"]["duration_seconds"],
                    "declare_status": row["declare"]["status"],
                    "declare_devs": row["declare"]["violation_count"],
                    "declare_unfit_traces": row["declare"]["extra"].get("unfit_traces"),
                    "declare_s": row["declare"]["duration_seconds"],
                }
            )

        report = {
            "declare_model": {
                "templates": sorted(DECLARE_MODEL_R1_R4),
                "constraints": {
                    name: [str(k) for k in bucket]
                    for name, bucket in DECLARE_MODEL_R1_R4.items()
                },
            },
            "clean_log_declare": result_to_dict(clean_declare),
            "per_rule": per_rule,
            "summary_table": summary,
            "interpretation": {
                "R1": "existence(Declaration SUBMITTED by EMPLOYEE)",
                "R2": "response(FINAL_APPROVED, Request Payment)",
                "R3": "precedence(Request Payment, Payment Handled)",
                "R4": "succession(Request Payment, Payment Handled)",
                "R5_R6": "KG-only domain rules; not part of the DECLARE baseline.",
            },
            "validation_engine": "sparql",
            "benchmarks_source": str(BENCH_ROOT),
        }
        out_json = OUT_ROOT / "comparison_report.json"
        out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

        lines = [
            "# DECLARE vs KG validation (10 declarations, R1–R4)",
            "",
            "DECLARE model: existence, response, precedence, succession.",
            "KG validation: SPARQL triple store.",
            f"Clean log DECLARE status: {clean_declare.status}, "
            f"deviations={clean_declare.violation_count}.",
            "",
            "| Rule | Inj. | KG det | KG s | DECLARE status | DECLARE devs | unfit traces | DECLARE s |",
            "|------|-----:|-------:|-----:|----------------|-------------:|-------------:|----------:|",
        ]
        for r in summary:
            lines.append(
                f"| {r['rule']} | {r['injected']} | {r['kg_detected']} | {r['kg_s']:.4f} | "
                f"{r['declare_status']} | {r['declare_devs']} | {r['declare_unfit_traces']} | "
                f"{r['declare_s']:.4f} |"
            )
        lines.extend(
            [
                "",
                "## Mapping",
                "",
                "- **R1**: existence(Declaration SUBMITTED by EMPLOYEE)",
                "- **R2**: response(FINAL_APPROVED, Request Payment)",
                "- **R3**: precedence(Request Payment, Payment Handled)",
                "- **R4**: succession(Request Payment, Payment Handled)",
                "",
            ]
        )
        md_path = OUT_ROOT / "comparison_report.md"
        md_path.write_text("\n".join(lines), encoding="utf-8")
        elog.log(f"Wrote {out_json}")
        elog.log(f"Wrote {md_path}")
        for r in summary:
            elog.log(
                f"{r['rule']}: inj={r['injected']} KG={r['kg_detected']} "
                f"DECLARE={r['declare_devs']} ({r['declare_status']})"
            )
        elog.log("DECLARE baseline comparison Done.")
    finally:
        sys.stdout = tee._out  # type: ignore[attr-defined]
        tee.close()


if __name__ == "__main__":
    main()
