"""Verify R1–R4: clean sanity, bench injection, case-level DECLARE vs KG agreement."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.generate_benchmark import BenchmarkConfig, RuleCorruptionConfig, generate_benchmark
from src.validate_declare_baseline import declare_model_for_rule, load_xes, run_declare_conformance
from src.validate_kg import validate_knowledge_graph
from src.validation_rules import DECLARE_MODEL_R1_R4, VALIDATION_RULES
from src.xes_to_prov_kg import convert_xes_to_prov_kg, load_graph

INP = ROOT / "dataset" / "DomesticDeclarations.sample_10declarations.xes"
OUT = ROOT / "benchmarks"
VAL_ROOT = ROOT / "output" / "declare_case_verification"


def _case_name_from_uri(uri: str) -> str:
    suffix = uri.rsplit("/", 1)[-1]
    if suffix.startswith("declaration_"):
        return "declaration " + suffix[len("declaration_") :]
    return suffix.replace("_", " ", 1)


def _rule(rule_id: str):
    return next(r for r in VALIDATION_RULES if r.rule_id == rule_id)


def _gen(rule: str, count: int = 5):
    enabled = {r: (r == rule) for r in ("r1", "r2", "r3", "r4")}
    cfg = BenchmarkConfig(
        config_path=ROOT / "benchmark.ini",
        input_path=INP,
        output_dir=OUT,
        seed=42,
        label="10declarations",
        r1=RuleCorruptionConfig(enabled["r1"], count if enabled["r1"] else None),
        r2=RuleCorruptionConfig(enabled["r2"], count if enabled["r2"] else None),
        r3=RuleCorruptionConfig(enabled["r3"], count if enabled["r3"] else None),
        r4=RuleCorruptionConfig(enabled["r4"], count if enabled["r4"] else None),
        r5=RuleCorruptionConfig(False),
        r5b=RuleCorruptionConfig(False),
        r6=RuleCorruptionConfig(False),
    )
    return generate_benchmark(cfg)


def _injected_cases(stats: dict, rule_id: str) -> set[str]:
    cases = set()
    for corr in stats.get("corruptions") or []:
        if corr.get("rule_id") != rule_id:
            continue
        tid = (corr.get("details") or {}).get("trace_id")
        if tid:
            cases.add(str(tid))
    return cases


def _kg_violated_cases(ttl: Path, rule_id: str, report_path: Path) -> tuple[set[str], int]:
    report = validate_knowledge_graph(
        load_graph(ttl),
        knowledge_graph_path=ttl,
        report_path=report_path,
        rules=(_rule(rule_id),),
    )
    cases = {
        _case_name_from_uri(v.details["case"])
        for v in report.results[0].violations
        if "case" in v.details
    }
    return cases, report.results[0].violation_count


def _declare_violated_cases(xes: Path, rule_id: str) -> tuple[set[str], int]:
    """Per-case DECLARE: a case is violated if its single-trace conformance fails."""
    log = load_xes(xes)
    model = declare_model_for_rule(rule_id)
    violated: set[str] = set()
    for case_id, group in log.groupby("case:concept:name", sort=False):
        result = run_declare_conformance(group.copy(), model)
        if result.status == "FAILED" or result.violation_count > 0:
            violated.add(str(case_id))
    # Also get aggregate deviation count on full log for reporting
    full = run_declare_conformance(log, model)
    return violated, full.violation_count


def main() -> None:
    VAL_ROOT.mkdir(parents=True, exist_ok=True)

    print("=== Clean log sanity ===")
    clean = load_xes(INP)
    clean_dec = run_declare_conformance(clean, DECLARE_MODEL_R1_R4)
    print(
        f"DECLARE full model on clean: status={clean_dec.status} "
        f"devs={clean_dec.violation_count}"
    )
    assert clean_dec.status == "PASSED" and clean_dec.violation_count == 0

    clean_ttl = VAL_ROOT / "clean.prov.ttl"
    convert_xes_to_prov_kg(INP, clean_ttl)
    clean_g = load_graph(clean_ttl)
    for rid in ("R1", "R2", "R3", "R4"):
        rep = validate_knowledge_graph(
            clean_g,
            knowledge_graph_path=clean_ttl,
            report_path=VAL_ROOT / f"clean_{rid.lower()}.json",
            rules=(_rule(rid),),
        )
        n = rep.results[0].violation_count
        print(f"KG {rid} on clean: {n}")
        assert n == 0, f"{rid} should pass on clean log"

    print("\n=== Per-rule case-level comparison ===")
    rows = []
    all_ok = True
    for rule in ("r1", "r2", "r3", "r4"):
        rid = rule.upper()
        stats_obj = _gen(rule)
        stats = json.loads(Path(stats_obj.outputs["statistics"]).read_text(encoding="utf-8"))
        injected = _injected_cases(stats, rid)
        applied = stats["applied"][rule]["applied"]
        ttl = Path(stats_obj.outputs["corrupted_knowledge_graph"])
        xes = Path(stats_obj.outputs["corrupted_xes"])

        kg_cases, kg_rows = _kg_violated_cases(ttl, rid, VAL_ROOT / f"kg_{rule}.json")
        dec_cases, dec_devs = _declare_violated_cases(xes, rid)

        same_cases = kg_cases == dec_cases
        covers_kg = injected <= kg_cases
        covers_dec = injected <= dec_cases
        ok = (
            applied == len(injected) == 5
            and covers_kg
            and covers_dec
            and same_cases
            and len(kg_cases) == len(dec_cases) == 5
        )
        all_ok = all_ok and ok
        mark = "OK" if ok else "FAIL"
        print(
            f"{mark} {rid}: injected={len(injected)} "
            f"KG_cases={len(kg_cases)} (rows={kg_rows}) "
            f"DECLARE_cases={len(dec_cases)} (devs={dec_devs}) "
            f"sets_equal={same_cases}"
        )
        if not same_cases:
            print(f"  only_KG={sorted(kg_cases - dec_cases)}")
            print(f"  only_DECLARE={sorted(dec_cases - kg_cases)}")
            print(f"  injected={sorted(injected)}")
        rows.append(
            {
                "rule": rid,
                "injected_cases": sorted(injected),
                "kg_cases": sorted(kg_cases),
                "declare_cases": sorted(dec_cases),
                "kg_rows": kg_rows,
                "declare_devs": dec_devs,
                "case_sets_equal": same_cases,
                "kg_covers_injected": covers_kg,
                "declare_covers_injected": covers_dec,
                "ok": ok,
            }
        )

    out = VAL_ROOT / "verification_report.json"
    out.write_text(json.dumps({"results": rows, "all_ok": all_ok}, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    if not all_ok:
        raise SystemExit(1)
    print("ALL CHECKS PASSED: R1–R4 case sets match between KG and DECLARE.")


if __name__ == "__main__":
    main()
