"""Visualize a PROV-O knowledge graph as interactive HTML using pyvis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pyvis.network import Network
from rdflib import Graph, URIRef
from rdflib.namespace import PROV, RDF, RDFS

from src.pipeline_config import load_pipeline_config
from src.xes_mapping import xes_attr_predicate
from src.xes_to_prov_kg import WF

ATTRIBUTE_NS = "http://www.xes-standard.org/attribute/"
NODE_STYLES = {
    PROV.Entity: {"color": "#97C2FC", "shape": "box", "group": "Entity"},
    PROV.Activity: {"color": "#FB7E81", "shape": "ellipse", "group": "Activity"},
    PROV.Agent: {"color": "#7BE141", "shape": "dot", "group": "Agent"},
}
EDGE_STYLES = {
    PROV.wasGeneratedBy: ("wasGeneratedBy", "entity<-activity"),
    PROV.wasInformedBy: ("wasInformedBy", "forward"),
    PROV.wasAssociatedWith: ("wasAssociatedWith", "forward"),
    PROV.used: ("used", "forward"),
    WF.belongsToCase: ("belongsToCase", "forward"),
}


@dataclass(frozen=True)
class VisualizationConfig:
    input_path: Path
    output_path: Path
    case_id: str | None = None


def visualize_prov_kg(graph: Graph, config: VisualizationConfig) -> Path:
    network = build_pyvis_network(graph, config)
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    network.write_html(str(config.output_path), notebook=False)
    return config.output_path


def build_pyvis_network(graph: Graph, config: VisualizationConfig) -> Network:
    network = Network(height="700px", width="100%", directed=True, notebook=False)
    network.barnes_hut(gravity=-12000, central_gravity=0.2, spring_length=180, spring_strength=0.04)

    case_uri = _case_uri(config.case_id) if config.case_id else None
    selected = _nodes_for_case(graph, case_uri) if case_uri else None
    seen_nodes: set[str] = set()

    for node in set(graph.subjects(RDF.type, None)):
        if not isinstance(node, URIRef):
            continue
        if selected is not None and node not in selected:
            continue
        node_type = _node_type(graph, node)
        if node_type is None:
            continue
        style = NODE_STYLES[node_type]
        node_id = str(node)
        if node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)
        network.add_node(
            node_id,
            label=_node_label(graph, node),
            title=node_id,
            color=style["color"],
            shape=style["shape"],
            group=style["group"],
        )

    for subject, predicate, object_ in graph.triples((None, None, None)):
        if predicate not in EDGE_STYLES:
            continue
        if not isinstance(subject, URIRef) or not isinstance(object_, URIRef):
            continue
        if selected is not None and (subject not in selected or object_ not in selected):
            continue
        source, target = _edge_endpoints(predicate, subject, object_)
        if str(source) not in seen_nodes or str(target) not in seen_nodes:
            continue
        network.add_edge(
            str(source),
            str(target),
            label=EDGE_STYLES[predicate][0],
            title=str(predicate),
        )

    return network


def run_from_config() -> Path:
    config = load_pipeline_config()
    if not config.output_path.is_file():
        raise FileNotFoundError(f"Knowledge graph not found: {config.output_path}")

    graph = Graph()
    graph.parse(config.output_path)
    output_path = visualize_prov_kg(
        graph,
        VisualizationConfig(
            input_path=config.output_path,
            output_path=config.visualization_path,
        ),
    )
    print(f"Wrote interactive graph visualization to {output_path}")
    return output_path


def _nodes_for_case(graph: Graph, case_uri: URIRef) -> set[URIRef]:
    selected = {case_uri}
    for subject, _, _ in graph.triples((None, WF.belongsToCase, case_uri)):
        selected.add(subject)
    for subject, predicate, object_ in graph.triples((None, None, None)):
        if predicate in {PROV.wasAssociatedWith, PROV.used, PROV.wasInformedBy, PROV.wasGeneratedBy}:
            if subject in selected:
                selected.add(object_)
            if object_ in selected:
                selected.add(subject)
    return selected


def _case_uri(case_id: str) -> URIRef:
    slug = case_id.strip().replace(" ", "_")
    return URIRef(f"http://kg.workflow.validation/case/{slug}")


def _node_type(graph: Graph, node: URIRef):
    for node_type in (PROV.Entity, PROV.Activity, PROV.Agent):
        if (node, RDF.type, node_type) in graph:
            return node_type
    return None


def _node_label(graph: Graph, node: URIRef) -> str:
    for predicate in graph.predicates(node, None):
        if str(predicate).endswith(xes_attr_predicate("concept:name")):
            value = graph.value(node, predicate)
            if value is not None:
                return str(value)
    label = graph.value(node, RDFS.label)
    if label is not None:
        return str(label)
    node_str = str(node)
    return node_str.rsplit("/", 1)[-1].replace("%20", " ") if "/" in node_str else node_str


def _edge_endpoints(predicate, subject: URIRef, object_: URIRef) -> tuple[URIRef, URIRef]:
    if EDGE_STYLES.get(predicate, ("", ""))[1] == "entity<-activity":
        return object_, subject
    return subject, object_


def main() -> None:
    run_from_config()


if __name__ == "__main__":
    main()
