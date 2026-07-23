"""Compare KG validation (R1–R4) with PM4Py DECLARE on 10-declaration benches."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.validate_declare_baseline import (
    declare_model_for_rule,
    load_xes,
    result_to_dict,
    run_declare_conformance,
)
from src.validate_kg import validate_knowledge_graph
from src.validation_rules import DECLARE_MODEL_R1_R4, VALIDATION_RULES
from src.xes_to_prov_kg import load_graph

BENCH_ROOT = ROOT / "benchmarks"
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


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rerun_kg(rule_id: str, ttl_path: Path, report_path: Path) -> dict:
    graph = load_graph(ttl_path)
    started = time.perf_counter()
    report = validate_knowledge_graph(
        graph,
        knowledge_graph_path=ttl_path,
        report_path=report_path,
        rules=(_rule_obj(rule_id),),
    )
    wall = round(time.perf_counter() - started, 6)
    row = report.results[0]
    return {
        "status": row.status,
        "violation_count": row.violation_count,
        "duration_seconds": row.duration_seconds,
        "wall_seconds": wall,
        "knowledge_graph": str(ttl_path),
        "report_path": str(report_path),
    }


def run_rule_comparison(rule_id: str) -> dict:
    bench = _bench_dir(rule_id)
    stats = _load_json(bench / "statistics.json")
    xes_path = Path(stats["outputs"]["corrupted_xes"])
    ttl_path = Path(stats["outputs"]["corrupted_knowledge_graph"])
    injected = stats.get("applied", {}).get(rule_id.lower(), {}).get("applied", 0)

    log = load_xes(xes_path)
    declare_res = run_declare_conformance(log, declare_model_for_rule(rule_id))
    kg = _rerun_kg(rule_id, ttl_path, OUT_ROOT / f"kg_rerun_{rule_id.lower()}" / "validation.json")

    return {
        "rule_id": rule_id,
        "benchmark": str(bench),
        "injected_count": injected,
        "declare": result_to_dict(declare_res),
        "kg": kg,
    }


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Sanity: clean log should fit the DECLARE model.
    clean = load_xes(CLEAN_XES)
    clean_declare = run_declare_conformance(clean, DECLARE_MODEL_R1_R4)

    per_rule = []
    for rule_id in RULES:
        print(f"Comparing {rule_id} ...")
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
    }
    out_json = OUT_ROOT / "comparison_report.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# DECLARE vs KG validation (10 declarations, R1–R4)",
        "",
        "DECLARE model: existence, response, precedence, succession.",
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
    print(f"Wrote {out_json}")
    print(f"Wrote {md_path}")
    for r in summary:
        print(
            f"{r['rule']}: inj={r['injected']} KG={r['kg_detected']} "
            f"DECLARE={r['declare_devs']} ({r['declare_status']})"
        )


if __name__ == "__main__":
    main()
