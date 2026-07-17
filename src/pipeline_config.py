"""Shared configuration for the KG workflow pipeline."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

from src.xes_mapping import MappingProfile, resolve_mapping_profile

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"
SUPPORTED_STAGES = ("conversion", "visualization")


@dataclass(frozen=True)
class PipelineConfig:
    config_path: Path
    input_path: Path
    output_path: Path
    stages: tuple[str, ...]
    mapping: MappingProfile

    @property
    def visualization_path(self) -> Path:
        return self.output_path.with_suffix(".html")


def _resolve_path(base_dir: Path, path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _parse_stages(value: str) -> tuple[str, ...]:
    stages = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    unknown = [stage for stage in stages if stage not in SUPPORTED_STAGES]
    if unknown:
        supported = ", ".join(SUPPORTED_STAGES)
        raise ValueError(
            f"Unsupported pipeline stages: {', '.join(unknown)}. "
            f"Supported values: {supported}"
        )
    if not stages:
        raise ValueError("At least one pipeline stage is required.")
    return stages


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
    output_value = section.get("output", "").strip()
    stages_value = section.get("stages", "").strip()
    if not input_value:
        raise ValueError("Config option 'input' is required in [pipeline].")
    if not output_value:
        raise ValueError("Config option 'output' is required in [pipeline].")
    if not stages_value:
        raise ValueError("Config option 'stages' is required in [pipeline].")

    base_dir = config_path.parent
    input_path = _resolve_path(base_dir, input_value)
    output_path = _resolve_path(base_dir, output_value)

    return PipelineConfig(
        config_path=config_path,
        input_path=input_path,
        output_path=output_path,
        stages=_parse_stages(stages_value),
        mapping=resolve_mapping_profile(input_path),
    )
