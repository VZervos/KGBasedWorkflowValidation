"""Shared configuration for the KG workflow pipeline."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.validation_rules import VALIDATION_RULES, ValidationRule

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class PipelineConfig:
    config_path: Path
    input_path: Path
    output_dir: Path
    run_dir: Path
    knowledge_graph_path: Path
    visualization_path: Path
    validation_report_path: Path
    statistics_path: Path
    conversion: bool
    visualization: bool
    validation: bool
    enabled_rules: tuple[str, ...]
    run_name: str

    def selected_validation_rules(self) -> tuple[ValidationRule, ...]:
        enabled = {rule_id.upper() for rule_id in self.enabled_rules}
        return tuple(rule for rule in VALIDATION_RULES if rule.rule_id.upper() in enabled)


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


def build_run_name(
    *,
    conversion: bool,
    visualization: bool,
    validation: bool,
    enabled_rules: tuple[str, ...],
    timestamp: datetime | None = None,
) -> str:
    parts = ["out"]
    if conversion:
        parts.append("conv")
    if visualization:
        parts.append("vis")
    if validation:
        parts.append("val")
        parts.extend(rule.lower() for rule in enabled_rules)
    stamp = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
    parts.append(stamp)
    return "_".join(parts)


def load_pipeline_config(config_path: Path = DEFAULT_CONFIG_PATH) -> PipelineConfig:
    config_path = config_path.resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(config_path, encoding="utf-8")
    if "pipeline" not in parser:
        raise ValueError(f"Missing [pipeline] section in config file: {config_path}")

    section = parser["pipeline"]
    input_value = section.get("input", "").strip()
    output_value = section.get("output_dir", section.get("output", "")).strip()
    existing_kg = section.get("knowledge_graph", "").strip()

    if not output_value:
        raise ValueError(
            "Config option 'output_dir' (or legacy 'output') is required in [pipeline]."
        )

    conversion = _parse_bool(section.get("conversion", "false"), option="conversion")
    visualization = _parse_bool(
        section.get("visualization", "false"), option="visualization"
    )
    validation = _parse_bool(section.get("validation", "false"), option="validation")

    if not (conversion or visualization or validation):
        raise ValueError(
            "At least one of conversion, visualization, or validation must be true."
        )

    base_dir = config_path.parent
    output_dir = _resolve_path(base_dir, output_value)

    if conversion and not input_value:
        raise ValueError("Config option 'input' is required when conversion = true.")

    input_path = (
        _resolve_path(base_dir, input_value)
        if input_value
        else Path()
    )

    known_rules = {rule.rule_id.upper() for rule in VALIDATION_RULES}
    enabled_rules: list[str] = []
    if "validation" in parser:
        for option, raw in parser["validation"].items():
            rule_id = option.strip().upper()
            if rule_id not in known_rules:
                known = ", ".join(sorted(known_rules)) or "(none yet)"
                raise ValueError(
                    f"Unknown validation rule '{option}' in [validation]. "
                    f"Known rules: {known}"
                )
            if _parse_bool(raw, option=f"validation.{option}"):
                enabled_rules.append(rule_id)

    if validation and not enabled_rules:
        raise ValueError(
            "validation = true but no rules are enabled in [validation] "
            "(e.g. R1 = true)."
        )

    run_name = build_run_name(
        conversion=conversion,
        visualization=visualization,
        validation=validation,
        enabled_rules=tuple(enabled_rules),
    )
    run_dir = output_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    dataset_stem = (
        input_path.name.replace(".xes.gz", "").replace(".xes", "")
        if input_value
        else "knowledge_graph"
    )
    produced_kg = run_dir / f"{dataset_stem}.prov.ttl"

    if conversion:
        knowledge_graph_path = produced_kg
    elif existing_kg:
        knowledge_graph_path = _resolve_path(base_dir, existing_kg)
    else:
        raise ValueError(
            "When conversion = false, set knowledge_graph to an existing .ttl file."
        )

    return PipelineConfig(
        config_path=config_path,
        input_path=input_path,
        output_dir=output_dir,
        run_dir=run_dir,
        knowledge_graph_path=knowledge_graph_path,
        visualization_path=run_dir / f"{dataset_stem}.prov.html",
        validation_report_path=run_dir / "validation.json",
        statistics_path=run_dir / "statistics.json",
        conversion=conversion,
        visualization=visualization,
        validation=validation,
        enabled_rules=tuple(enabled_rules),
        run_name=run_name,
    )
