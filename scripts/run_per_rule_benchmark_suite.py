"""Generate one benchmark per rule per dataset and verify validation results."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
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
# Rules where one corruption can surface as multiple SPARQL rows.
MULTI_VIOLATION_RULES = frozenset({"R2", "R4", "R6"})

# Config files live under benchmarks/; inputs are relative to that directory.
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


@dataclass
class SuiteResult:
    dataset: str
    rule: str
    bench_dir: str
    applied: int
    violations: int
    status: str
    ok: bool
    note: str = ""


def _benchmark_ini(dataset: dict, rule: str) -> str:
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
        if r == rule:
            sections.append("enabled = true")
            sections.append(f"count = {dataset['count']}")
        else:
            sections.append("enabled = false")
        sections.append("")
    return "\n".join(sections)


def _rule_by_id(rule_id: str):
    for rule in VALIDATION_RULES:
        if rule.rule_id == rule_id:
            return rule
    raise KeyError(rule_id)


def _verify_result(
    *,
    dataset: dict,
    rule: str,
    applied: int,
    violations: int,
    corruptions: list[dict],
) -> tuple[bool, str]:
    rule_id = RULE_ID_MAP[rule]
    if applied == 0:
        return False, "no corruptions applied"

    if rule_id in MULTI_VIOLATION_RULES:
        if violations < applied:
            return False, f"violations {violations} < applied {applied}"
        return True, f"violations {violations} >= applied {applied}"

    if violations != applied:
        return False, f"violations {violations} != applied {applied}"
    return True, "exact match"


def main() -> None:
    BENCH_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results: list[SuiteResult] = []

    for dataset in DATASETS:
        print(f"\n=== Dataset: {dataset['name']} ===", flush=True)
        for rule in RULES:
            rule_id = RULE_ID_MAP[rule]
            cfg_path = BENCH_ROOT / f"_suite_{dataset['name']}_{rule}.ini"
            cfg_path.write_text(_benchmark_ini(dataset, rule), encoding="utf-8")

            print(f"  [{rule_id}] generating benchmark...", flush=True)
            stats = generate_benchmark(load_benchmark_config(cfg_path))
            bench_stats = json.loads(
                Path(stats.outputs["statistics"]).read_text(encoding="utf-8")
            )
            applied = bench_stats["applied"][rule]["applied"]
            ttl = Path(stats.outputs["corrupted_knowledge_graph"])

            print(f"  [{rule_id}] validating...", flush=True)
            graph = load_graph(ttl)
            rule_obj = _rule_by_id(rule_id)
            val_dir = OUT_ROOT / f"val_{rule}_{dataset['name']}"
            val_dir.mkdir(parents=True, exist_ok=True)
            report_path = val_dir / "validation.json"
            report = validate_knowledge_graph(
                graph,
                knowledge_graph_path=ttl,
                report_path=report_path,
                rules=(rule_obj,),
            )
            result = report.results[0]
            ok, note = _verify_result(
                dataset=dataset,
                rule=rule,
                applied=applied,
                violations=result.violation_count,
                corruptions=bench_stats["corruptions"],
            )
            status = "PASS" if ok else "FAIL"
            print(
                f"  [{rule_id}] {status}: applied={applied}, "
                f"violations={result.violation_count} ({note})",
                flush=True,
            )
            results.append(
                SuiteResult(
                    dataset=dataset["name"],
                    rule=rule_id,
                    bench_dir=stats.run_dir,
                    applied=applied,
                    violations=result.violation_count,
                    status=status,
                    ok=ok,
                    note=note,
                )
            )

    summary = {
        "datasets": list(d["name"] for d in DATASETS),
        "rules": [RULE_ID_MAP[r] for r in RULES],
        "results": [r.__dict__ for r in results],
        "passed": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if not r.ok),
    }
    summary_path = OUT_ROOT / "suite_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n=== Summary ===", flush=True)
    for r in results:
        mark = "OK" if r.ok else "FAIL"
        print(
            f"{mark} {r.dataset}/{r.rule}: applied={r.applied}, "
            f"violations={r.violations} -> {r.bench_dir}",
            flush=True,
        )
    print(
        f"\nPassed {summary['passed']}/{len(results)}. Summary: {summary_path}",
        flush=True,
    )
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
