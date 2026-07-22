"""Rename current experiment benches/outputs to stable searchable names.

Examples:
  benchmarks/bench_r1_full
  benchmarks/bench_all_10declarations
  output/per_rule_validation/val_r1_full
  output/per_rule_validation/val_all_10declarations
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH_ROOT = ROOT / "benchmarks"
OUT_ROOT = ROOT / "output" / "per_rule_validation"

RULES = ("r1", "r2", "r3", "r4", "r5", "r5b", "r6")
DATASETS = ("10declarations", "full")


def _latest(matches: list[Path]) -> Path | None:
    return sorted(matches, key=lambda p: p.name)[-1] if matches else None


def _rewrite_stats(bench_dir: Path, run_name: str) -> None:
    stats_path = bench_dir / "statistics.json"
    if not stats_path.is_file():
        return
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    stats["run_name"] = run_name
    stats["run_dir"] = str(bench_dir)
    for key, value in list(stats.get("outputs", {}).items()):
        old = Path(value)
        stats["outputs"][key] = str(bench_dir / old.name)
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")


def _rewrite_validation(val_dir: Path, kg_path: Path | None) -> None:
    val_path = val_dir / "validation.json"
    if not val_path.is_file():
        return
    payload = json.loads(val_path.read_text(encoding="utf-8"))
    if kg_path is not None:
        payload["knowledge_graph"] = str(kg_path)
    payload["report_path"] = str(val_path)
    val_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _move_dir(src: Path, dest: Path) -> None:
    if not src.exists():
        print(f"  skip missing {src}")
        return
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    print(f"  {src.relative_to(ROOT)} -> {dest.relative_to(ROOT)}")


def rename_benchmarks() -> dict[tuple[str, str], Path]:
    """Return mapping (dataset, rule_or_all) -> new bench dir."""
    mapping: dict[tuple[str, str], Path] = {}
    print("=== Renaming benchmarks ===")
    for dataset in DATASETS:
        parent = BENCH_ROOT / dataset
        if not parent.is_dir():
            continue

        for rule in RULES:
            latest = _latest(
                [
                    p
                    for p in parent.glob(f"bench_{rule}_*")
                    if re.fullmatch(rf"bench_{rule}_\d{{8}}_\d{{6}}", p.name)
                ]
            )
            # Also accept already-new names inside dataset folder.
            if latest is None:
                candidate = parent / f"bench_{rule}_{dataset}"
                if candidate.is_dir():
                    latest = candidate
            if latest is None:
                print(f"  missing {dataset}/{rule}")
                continue
            dest = BENCH_ROOT / f"bench_{rule}_{dataset}"
            _move_dir(latest, dest)
            _rewrite_stats(dest, dest.name)
            mapping[(dataset, rule)] = dest

        combined = _latest(
            [
                p
                for p in parent.glob("bench_r1_r2_r3_r4_r5_r5b_r6_*")
                if p.is_dir()
            ]
        )
        if combined is None:
            candidate = parent / f"bench_all_{dataset}"
            if candidate.is_dir():
                combined = candidate
        if combined is not None:
            dest = BENCH_ROOT / f"bench_all_{dataset}"
            _move_dir(combined, dest)
            _rewrite_stats(dest, dest.name)
            mapping[(dataset, "all")] = dest

        # Remove obsolete leftover timestamped dirs under dataset folders.
        if parent.is_dir():
            for leftover in list(parent.iterdir()):
                if leftover.is_dir() and leftover.name.startswith("bench_"):
                    print(f"  removing obsolete {leftover.relative_to(ROOT)}")
                    shutil.rmtree(leftover)
            # Remove empty dataset folder.
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                print(f"  removed empty {parent.relative_to(ROOT)}")

    return mapping


def rename_outputs(bench_map: dict[tuple[str, str], Path]) -> None:
    print("\n=== Renaming validation outputs ===")
    for dataset in DATASETS:
        parent = OUT_ROOT / dataset
        if not parent.is_dir():
            continue

        for rule in (*RULES, "all"):
            src = parent / rule
            if not src.is_dir():
                continue
            dest = OUT_ROOT / f"val_{rule}_{dataset}"
            _move_dir(src, dest)
            kg = None
            bench = bench_map.get((dataset, rule))
            if bench is not None:
                ttls = list(bench.glob("*.corrupted.prov.ttl"))
                if ttls:
                    kg = ttls[0]
            _rewrite_validation(dest, kg)

        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            print(f"  removed empty {parent.relative_to(ROOT)}")


def patch_report(bench_map: dict[tuple[str, str], Path]) -> None:
    print("\n=== Patching experiment report paths ===")
    json_path = OUT_ROOT / "experiment_report.json"
    md_path = OUT_ROOT / "experiment_report.md"

    if json_path.is_file():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        _patch_json_paths(data, bench_map)
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"  updated {json_path.name}")

    if md_path.is_file():
        text = md_path.read_text(encoding="utf-8")
        for (dataset, rule), bench in bench_map.items():
            val_dir = OUT_ROOT / f"val_{rule}_{dataset}"

            def _sub_bench(pattern: str, target: Path, body: str) -> str:
                return re.sub(pattern, lambda _m: str(target), body)

            text = _sub_bench(
                rf"benchmarks[/\\]{re.escape(dataset)}[/\\]bench_{re.escape(rule)}_\d{{8}}_\d{{6}}",
                Path("benchmarks") / bench.name,
                text,
            )
            if rule == "all":
                text = _sub_bench(
                    rf"benchmarks[/\\]{re.escape(dataset)}[/\\]bench_r1_r2_r3_r4_r5_r5b_r6_\d{{8}}_\d{{6}}",
                    Path("benchmarks") / bench.name,
                    text,
                )
            # Prefer forward slashes in relative markdown paths.
            text = text.replace(
                f"benchmarks\\{bench.name}",
                f"benchmarks/{bench.name}",
            )
            text = text.replace(
                f"per_rule_validation/{dataset}/{rule}",
                f"per_rule_validation/val_{rule}_{dataset}",
            )
            text = text.replace(
                f"per_rule_validation\\{dataset}\\{rule}",
                f"per_rule_validation\\val_{rule}_{dataset}",
            )
            old_abs_prefix = str(BENCH_ROOT / dataset)
            text = text.replace(old_abs_prefix + "\\", str(BENCH_ROOT) + "\\")
            text = text.replace(old_abs_prefix + "/", str(BENCH_ROOT) + "/")
            old_val_prefix = str(OUT_ROOT / dataset / rule)
            text = text.replace(old_val_prefix, str(val_dir))
            text = _sub_bench(
                re.escape(str(BENCH_ROOT))
                + rf"[/\\]bench_{re.escape(rule)}_\d{{8}}_\d{{6}}",
                bench,
                text,
            )
            if rule == "all":
                text = _sub_bench(
                    re.escape(str(BENCH_ROOT))
                    + r"[/\\]bench_r1_r2_r3_r4_r5_r5b_r6_\d{8}_\d{6}",
                    bench,
                    text,
                )
        md_path.write_text(text, encoding="utf-8")
        print(f"  updated {md_path.name}")


def _patch_json_paths(data: dict, bench_map: dict[tuple[str, str], Path]) -> None:
    def fix_case(case: dict, dataset: str, rule: str) -> None:
        key = rule.lower()
        bench = bench_map.get((dataset, key))
        if bench is None:
            return
        case["bench_dir"] = str(bench)
        case["bench_run_name"] = bench.name
        if "validation_report" in case:
            case["validation_report"] = str(
                OUT_ROOT / f"val_{key}_{dataset}" / "validation.json"
            )

    for case in data.get("cases", []):
        fix_case(case, case.get("dataset", ""), case.get("rule", ""))
    for case in data.get("combined_cases", []):
        fix_case(case, case.get("dataset", ""), "all")
    for item in data.get("r4_regeneration", []):
        fix_case(item, item.get("dataset", ""), "r4")


def main() -> None:
    bench_map = rename_benchmarks()
    rename_outputs(bench_map)
    patch_report(bench_map)
    print("\nDone. Current layout:")
    for p in sorted(BENCH_ROOT.glob("bench_*")):
        if p.is_dir():
            print(f"  {p.relative_to(ROOT)}")
    for p in sorted(OUT_ROOT.glob("val_*")):
        if p.is_dir():
            print(f"  {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
