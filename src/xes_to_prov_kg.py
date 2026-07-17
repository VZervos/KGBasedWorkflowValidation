"""Stream XES event logs into PROV-O knowledge graphs.

Uses an XES-standard mapping profile with optional config overrides.
Extensions, attribute types, and identity keys are resolved from the file.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from src.pipeline_config import load_pipeline_config
from src.xes_mapping import (
    MappingProfile,
    XesAttribute,
    first_value,
    matched_key,
    read_attributes,
    resolve_mapping_profile,
    xes_attr_uri,
)

PROV = Namespace("http://www.w3.org/ns/prov#")
XES = Namespace("http://www.xes-standard.org/")
XES_ATTR = Namespace("http://www.xes-standard.org/attribute/")
WF = Namespace("http://kg.workflow.validation/")
BASE = "http://kg.workflow.validation/"

GENERIC_AGENT_RESOURCES = frozenset({
    "STAFF MEMBER",
    "SYSTEM",
    "UNKNOWN",
    "MISSING",
})

RDF_FORMATS = {
    ".ttl": "turtle",
    ".turtle": "turtle",
    ".nt": "nt",
    ".json": "json-ld",
    ".jsonld": "json-ld",
    ".nq": "nquads",
    ".nquads": "nquads",
    ".trig": "trig",
}


@dataclass(frozen=True)
class Event:
    event_id: str
    name: str
    timestamp: str
    resource: str
    role: str
    resource_key: str
    role_key: str
    attrs: dict[str, XesAttribute] = field(default_factory=dict)


@dataclass(frozen=True)
class Trace:
    trace_id: str
    name: str
    attrs: dict[str, XesAttribute]
    events: list[Event]


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    trace_count: int
    triple_count: int
    mapping: MappingProfile


def convert_xes_to_prov_kg(
    input_path: Path,
    output_path: Path,
    *,
    rdf_format: str | None = None,
    mapping: MappingProfile | None = None,
) -> ConversionResult:
    profile = mapping or resolve_mapping_profile(input_path)
    fmt = rdf_format or RDF_FORMATS.get(output_path.suffix.lower(), "turtle")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    traces = triples = 0
    agents_seen: set[str] = set()
    wrote_header = False

    with output_path.open("w", encoding="utf-8") as out:
        for trace in _iter_traces(input_path, profile):
            traces += 1
            chunk = Graph()
            _bind_namespaces(chunk)
            triples += _add_trace(chunk, trace, profile, agents_seen)
            text = chunk.serialize(format=fmt)
            if fmt == "turtle" and wrote_header:
                text = "\n".join(
                    line for line in text.splitlines()
                    if line.strip() and not line.startswith("@prefix")
                ) + "\n"
            out.write(text if text.endswith("\n") else text + "\n")
            wrote_header = True

    return ConversionResult(output_path, traces, triples, profile)


def load_graph(path: Path) -> Graph:
    graph = Graph()
    graph.parse(path)
    return graph


def run_from_config() -> ConversionResult:
    config = load_pipeline_config()
    if not config.input_path.is_file():
        raise FileNotFoundError(f"Input XES file not found: {config.input_path}")

    result = convert_xes_to_prov_kg(
        config.input_path,
        config.output_path,
        mapping=config.mapping,
    )
    print(
        f"Wrote {result.triple_count} triples from {result.trace_count} traces "
        f"to {result.output_path}"
    )
    return result


def _iter_traces(path: Path, profile: MappingProfile) -> Iterator[Trace]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            if _tag(elem) != "trace":
                continue
            trace = _parse_trace(elem, profile)
            elem.clear()
            if trace:
                yield trace


def _parse_trace(elem: ET.Element, profile: MappingProfile) -> Trace | None:
    attrs = read_attributes(elem, profile)
    trace_id = first_value(attrs, profile.case_id_keys)
    if not trace_id:
        return None

    events = [e for child in elem.findall("event") if (e := _parse_event(child, profile))]
    events.sort(key=lambda item: item.timestamp)

    return Trace(
        trace_id=trace_id,
        name=first_value(attrs, profile.case_name_keys) or trace_id,
        attrs=attrs,
        events=events,
    )


def _parse_event(elem: ET.Element, profile: MappingProfile) -> Event | None:
    attrs = read_attributes(elem, profile)
    event_id = first_value(attrs, profile.event_id_keys)
    name = first_value(attrs, profile.activity_label_keys)
    if not event_id or not name:
        return None

    return Event(
        event_id=event_id,
        name=name,
        timestamp=first_value(attrs, profile.timestamp_keys) or "",
        resource=first_value(attrs, profile.agent_resource_keys) or "UNKNOWN",
        role=first_value(attrs, profile.agent_role_keys) or "UNKNOWN",
        resource_key=matched_key(attrs, profile.agent_resource_keys) or profile.agent_resource_keys[0],
        role_key=matched_key(attrs, profile.agent_role_keys) or profile.agent_role_keys[0],
        attrs=attrs,
    )


def _add_trace(
    graph: Graph,
    trace: Trace,
    profile: MappingProfile,
    agents_seen: set[str],
) -> int:
    start = len(graph)
    case = _uri("case", trace.trace_id)
    resource_roles = _resource_roles(trace.events)

    graph.add((case, RDF.type, PROV.Entity))
    graph.add((case, RDFS.label, Literal(trace.name)))
    _apply_xes_attributes(graph, case, trace.attrs)
    _set_xes(graph, case, "id", trace.trace_id)

    prev_activity = None
    for event in trace.events:
        activity = _uri("activity", event.event_id)
        agent = _uri("agent", _agent_slug(event.resource, event.role, resource_roles[event.resource]))

        graph.add((activity, RDF.type, PROV.Activity))
        graph.add((activity, RDFS.label, Literal(event.name)))
        _apply_xes_attributes(graph, activity, event.attrs)
        _set_xes(graph, activity, "id", event.event_id)
        if event.timestamp:
            ts = _datetime(event.timestamp)
            graph.add((activity, PROV.startedAtTime, ts))
            graph.add((activity, PROV.endedAtTime, ts))

        agent_key = str(agent)
        if agent_key not in agents_seen:
            agents_seen.add(agent_key)
            graph.add((agent, RDF.type, PROV.Agent))
            graph.add((agent, RDFS.label, Literal(event.resource)))
            _set_xes(graph, agent, event.resource_key, event.resource)
            _set_xes(graph, agent, event.role_key, event.role)

        graph.add((activity, PROV.wasAssociatedWith, agent))
        graph.add((activity, WF.belongsToCase, case))
        graph.add((activity, PROV.used, case))
        if prev_activity is None:
            graph.add((case, PROV.wasGeneratedBy, activity))
        if prev_activity is not None:
            graph.add((activity, PROV.wasInformedBy, prev_activity))

        prev_activity = activity

    return len(graph) - start


def _resource_roles(events: list[Event]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for event in events:
        mapping.setdefault(event.resource, set()).add(event.role)
    return mapping


def _agent_slug(resource: str, role: str, roles_for_resource: set[str]) -> str:
    normalized = resource.strip()
    if normalized.upper() in GENERIC_AGENT_RESOURCES or len(roles_for_resource) > 1:
        return f"{normalized}::{role.strip()}"
    return normalized


def _bind_namespaces(graph: Graph) -> None:
    graph.bind("prov", PROV)
    graph.bind("xes", XES)
    graph.bind("attr", XES_ATTR)
    graph.bind("wf", WF)
    graph.bind("rdfs", RDFS)


def _uri(kind: str, value: str) -> URIRef:
    slug = quote(value.strip().replace(" ", "_"), safe="")
    return URIRef(f"{BASE}{kind}/{slug}")


def _xes_attr(key: str) -> URIRef:
    return URIRef(xes_attr_uri(key))


def _apply_xes_attributes(
    graph: Graph,
    subject: URIRef,
    attributes: dict[str, XesAttribute],
) -> None:
    for attribute in attributes.values():
        _set_xes_typed(graph, subject, attribute)


def _set_xes(graph: Graph, subject: URIRef, key: str, value: str) -> None:
    graph.add((subject, _xes_attr(key), _literal_from_type(value, "string")))


def _set_xes_typed(graph: Graph, subject: URIRef, attribute: XesAttribute) -> None:
    if not attribute.value:
        return
    graph.add(
        (
            subject,
            _xes_attr(attribute.key),
            _literal_from_type(attribute.value, attribute.value_type),
        )
    )


def _literal_from_type(value: str, value_type: str) -> Literal:
    if value_type == "date":
        return _datetime(value)
    if value_type == "int":
        try:
            return Literal(int(value), datatype=XSD.integer)
        except ValueError:
            return Literal(value)
    if value_type == "float":
        try:
            return Literal(float(value), datatype=XSD.double)
        except ValueError:
            return Literal(value)
    if value_type == "boolean":
        return Literal(value.lower() in {"true", "1", "yes"}, datatype=XSD.boolean)
    return Literal(value)


def _datetime(value: str) -> Literal:
    try:
        return Literal(
            datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat(),
            datatype=XSD.dateTime,
        )
    except ValueError:
        return Literal(value, datatype=XSD.string)


def _tag(elem: ET.Element) -> str:
    return elem.tag.rsplit("}", 1)[-1]


__all__ = [
    "ConversionResult",
    "convert_xes_to_prov_kg",
    "load_graph",
    "WF",
]


def main() -> None:
    run_from_config()


if __name__ == "__main__":
    main()
