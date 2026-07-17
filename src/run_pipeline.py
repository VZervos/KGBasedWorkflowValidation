"""Run the configurable KG workflow pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph

from src.pipeline_config import PipelineConfig, load_pipeline_config
from src.visualize_prov_kg import VisualizationConfig, visualize_prov_kg
from src.xes_to_prov_kg import convert_xes_to_prov_kg, load_graph


@dataclass(frozen=True)
class StageResult:
    stage: str
    status: str
    details: str


@dataclass(frozen=True)
class PipelineResult:
    input_path: Path
    output_path: Path
    stage_results: tuple[StageResult, ...]


def _run_conversion(config: PipelineConfig) -> StageResult:
    if not config.input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {config.input_path}")

    result = convert_xes_to_prov_kg(
        config.input_path,
        config.output_path,
        mapping=config.mapping,
    )
    return StageResult(
        stage="conversion",
        status="completed",
        details=(
            f"Built knowledge graph with {result.triple_count} triples from "
            f"{result.trace_count} traces at {config.output_path}"
        ),
    )


def _run_visualization(config: PipelineConfig, graph: Graph) -> StageResult:
    output_path = visualize_prov_kg(
        graph,
        VisualizationConfig(
            input_path=config.output_path,
            output_path=config.visualization_path,
        ),
    )
    return StageResult(
        stage="visualization",
        status="completed",
        details=f"Interactive visualization written to {output_path}",
    )


def run_pipeline(config: PipelineConfig) -> PipelineResult:
    stage_results: list[StageResult] = []
    graph: Graph | None = None

    if "conversion" in config.stages:
        stage_results.append(_run_conversion(config))
    elif "visualization" in config.stages:
        if not config.output_path.is_file():
            raise FileNotFoundError(
                "Knowledge graph not found. Run conversion first or set "
                f"output to an existing graph: {config.output_path}"
            )

    if "visualization" in config.stages:
        graph = graph or load_graph(config.output_path)
        stage_results.append(_run_visualization(config, graph))

    print("Pipeline stage results:\n")
    for result in stage_results:
        print(f"- {result.stage}: {result.status}")
        print(f"  {result.details}")

    return PipelineResult(
        input_path=config.input_path,
        output_path=config.output_path,
        stage_results=tuple(stage_results),
    )


def run_from_config(config_path: Path | None = None) -> PipelineResult:
    from src.pipeline_config import DEFAULT_CONFIG_PATH

    config = load_pipeline_config(config_path or DEFAULT_CONFIG_PATH)
    print(f"Input: {config.input_path}")
    print(f"Output: {config.output_path}")
    print(f"Stages: {', '.join(config.stages)}")
    return run_pipeline(config)


def main() -> None:
    run_from_config()


if __name__ == "__main__":
    main()
