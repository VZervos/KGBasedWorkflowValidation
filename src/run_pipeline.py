"""Run the configurable KG workflow pipeline."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Graph

from src.pipeline_config import PipelineConfig, load_pipeline_config
from src.validate_kg import ValidationReport, log_validation_summary, validate_knowledge_graph
from src.visualize_prov_kg import VisualizationConfig, visualize_prov_kg
from src.xes_to_prov_kg import ConversionResult, convert_xes_to_prov_kg, load_graph


@dataclass(frozen=True)
class StageResult:
    stage: str
    status: str
    details: str
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class PipelineResult:
    input_path: Path
    run_dir: Path
    stage_results: tuple[StageResult, ...]
    statistics_path: Path


def _run_conversion(config: PipelineConfig) -> tuple[StageResult, ConversionResult]:
    if not config.input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {config.input_path}")

    result = convert_xes_to_prov_kg(config.input_path, config.knowledge_graph_path)
    return (
        StageResult(
            stage="conversion",
            status="completed",
            details=(
                f"Built knowledge graph with {result.stats.triple_count} triples from "
                f"{result.stats.trace_count} traces at {config.knowledge_graph_path}"
            ),
            duration_seconds=result.stats.duration_seconds,
        ),
        result,
    )


def _run_visualization(config: PipelineConfig, graph: Graph) -> StageResult:
    started = time.perf_counter()
    output_path = visualize_prov_kg(
        graph,
        VisualizationConfig(
            input_path=config.knowledge_graph_path,
            output_path=config.visualization_path,
        ),
    )
    duration = round(time.perf_counter() - started, 6)
    return StageResult(
        stage="visualization",
        status="completed",
        details=f"Interactive visualization written to {output_path}",
        duration_seconds=duration,
    )


def _run_validation(
    config: PipelineConfig,
    graph: Graph,
) -> tuple[StageResult, ValidationReport]:
    rules = config.selected_validation_rules()
    report = validate_knowledge_graph(
        graph,
        knowledge_graph_path=config.knowledge_graph_path,
        report_path=config.validation_report_path,
        rules=rules,
    )
    log_validation_summary(report)
    return (
        StageResult(
            stage="validation",
            status="passed" if report.passed else "failed",
            details=(
                f"Validation {report.status}; report at {config.validation_report_path}"
            ),
            duration_seconds=report.duration_seconds,
        ),
        report,
    )


def _write_statistics(
    config: PipelineConfig,
    *,
    pipeline_started_at: str,
    pipeline_finished_at: str,
    pipeline_duration_seconds: float,
    stage_results: list[StageResult],
    conversion: ConversionResult | None,
    validation: ValidationReport | None,
    graph_load_seconds: float | None,
) -> None:
    stages = {
        result.stage: {
            "status": result.status,
            "duration_seconds": result.duration_seconds,
            "details": result.details,
        }
        for result in stage_results
    }

    payload: dict = {
        "run_name": config.run_name,
        "run_dir": str(config.run_dir),
        "started_at": pipeline_started_at,
        "finished_at": pipeline_finished_at,
        "total_duration_seconds": pipeline_duration_seconds,
        "input": str(config.input_path) if config.input_path else None,
        "knowledge_graph": str(config.knowledge_graph_path),
        "enabled": {
            "conversion": config.conversion,
            "visualization": config.visualization,
            "validation": config.validation,
            "rules": list(config.enabled_rules),
        },
        "outputs": {
            "knowledge_graph": str(config.knowledge_graph_path)
            if config.knowledge_graph_path.is_file()
            else None,
            "visualization": str(config.visualization_path)
            if config.visualization_path.is_file()
            else None,
            "validation_report": str(config.validation_report_path)
            if config.validation_report_path.is_file()
            else None,
            "statistics": str(config.statistics_path),
        },
        "stages": stages,
    }

    if graph_load_seconds is not None:
        payload["graph_load_seconds"] = graph_load_seconds

    if conversion is not None:
        payload["conversion"] = asdict(conversion.stats)
        payload["conversion"]["output_path"] = str(conversion.output_path)

    if validation is not None:
        payload["validation"] = {
            "status": validation.status,
            "duration_seconds": validation.duration_seconds,
            "total_violations": validation.total_violations,
            "rules_run": list(validation.rules_run),
            "rules": [
                {
                    "rule_id": result.rule_id,
                    "name": result.name,
                    "status": result.status,
                    "violation_count": result.violation_count,
                    "duration_seconds": result.duration_seconds,
                }
                for result in validation.results
            ],
        }

    config.statistics_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_pipeline(config: PipelineConfig) -> PipelineResult:
    stage_results: list[StageResult] = []
    graph: Graph | None = None
    conversion_result: ConversionResult | None = None
    validation_report: ValidationReport | None = None
    graph_load_seconds: float | None = None

    pipeline_started_at = datetime.now(timezone.utc).isoformat()
    pipeline_started = time.perf_counter()

    needs_existing_graph = (
        config.visualization or config.validation
    ) and not config.conversion

    if config.conversion:
        stage, conversion_result = _run_conversion(config)
        stage_results.append(stage)
    elif needs_existing_graph:
        if not config.knowledge_graph_path.is_file():
            raise FileNotFoundError(
                "Knowledge graph not found. Run conversion first or set "
                f"knowledge_graph to an existing file: {config.knowledge_graph_path}"
            )

    if config.visualization or config.validation:
        load_started = time.perf_counter()
        graph = load_graph(config.knowledge_graph_path)
        graph_load_seconds = round(time.perf_counter() - load_started, 6)

    if config.visualization:
        assert graph is not None
        stage_results.append(_run_visualization(config, graph))

    if config.validation:
        assert graph is not None
        stage, validation_report = _run_validation(config, graph)
        stage_results.append(stage)

    pipeline_duration = round(time.perf_counter() - pipeline_started, 6)
    pipeline_finished_at = datetime.now(timezone.utc).isoformat()

    _write_statistics(
        config,
        pipeline_started_at=pipeline_started_at,
        pipeline_finished_at=pipeline_finished_at,
        pipeline_duration_seconds=pipeline_duration,
        stage_results=stage_results,
        conversion=conversion_result,
        validation=validation_report,
        graph_load_seconds=graph_load_seconds,
    )

    print("Pipeline stage results:\n")
    for result in stage_results:
        print(f"- {result.stage}: {result.status} ({result.duration_seconds:.4f}s)")
        print(f"  {result.details}")
    print(f"\nRun directory: {config.run_dir}")
    print(f"Statistics: {config.statistics_path}")

    return PipelineResult(
        input_path=config.input_path,
        run_dir=config.run_dir,
        stage_results=tuple(stage_results),
        statistics_path=config.statistics_path,
    )


def run_from_config(config_path: Path | None = None) -> PipelineResult:
    from src.pipeline_config import DEFAULT_CONFIG_PATH

    config = load_pipeline_config(config_path or DEFAULT_CONFIG_PATH)
    print(f"Input: {config.input_path if config.input_path else '(none)'}")
    print(f"Run directory: {config.run_dir}")
    print(
        "Enabled: "
        f"conversion={config.conversion}, "
        f"visualization={config.visualization}, "
        f"validation={config.validation}"
    )
    if config.validation:
        print(f"Validation rules: {', '.join(config.enabled_rules) or '(none)'}")
    return run_pipeline(config)


def main() -> None:
    run_from_config()


if __name__ == "__main__":
    main()
