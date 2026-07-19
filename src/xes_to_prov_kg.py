"""Stream XES event logs into PROV-O knowledge graphs.

Missing or incomplete XES fields are not filled with defaults. Construction
emits a console warning and continues when possible so validation can catch
integrity problems later.
"""

from __future__ import annotations

import gzip
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from src.pipeline_config import load_pipeline_config

PROV = Namespace("http://www.w3.org/ns/prov#")
ATTR = Namespace("http://www.xes-standard.org/attribute/")
WF = Namespace("http://kg.workflow.validation/")
BASE = "http://kg.workflow.validation/"

CASE_ID_KEY = "id"
CASE_NAME_KEY = "concept:name"
EVENT_ID_KEY = "id"
ACTIVITY_KEY = "concept:name"
TIMESTAMP_KEY = "time:timestamp"
RESOURCE_KEY = "org:resource"
ROLE_KEY = "org:role"

VALUE_TYPES = frozenset({"string", "date", "int", "float", "boolean"})


@dataclass
class ConversionStats:
    xes_lines_parsed: int = 0
    trace_count: int = 0
    event_count: int = 0
    triple_count: int = 0
    agent_count: int = 0
    skipped_traces: int = 0
    skipped_events: int = 0
    warning_count: int = 0
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    stats: ConversionStats


def convert_xes_to_prov_kg(input_path: Path, output_path: Path) -> ConversionResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stats = ConversionStats()
    agents_seen: set[str] = set()
    wrote_header = False
    started = time.perf_counter()

    stats.xes_lines_parsed = _count_xes_lines(input_path)

    with output_path.open("w", encoding="utf-8") as out:
        for trace_id, name, attrs, events, skip_info in _iter_traces(input_path, stats):
            stats.trace_count += 1
            stats.event_count += len(events)
            stats.skipped_events += skip_info

            chunk = Graph()
            _bind(chunk)
            stats.triple_count += _emit_trace(
                chunk, trace_id, name, attrs, events, agents_seen, stats
            )
            text = chunk.serialize(format="turtle")
            if wrote_header:
                text = "\n".join(
                    line for line in text.splitlines()
                    if line.strip() and not line.startswith("@prefix")
                ) + "\n"
            out.write(text if text.endswith("\n") else text + "\n")
            wrote_header = True

    stats.agent_count = len(agents_seen)
    stats.duration_seconds = round(time.perf_counter() - started, 6)
    return ConversionResult(output_path, stats)


def load_graph(path: Path) -> Graph:
    graph = Graph()
    graph.parse(path)
    return graph


def run_from_config() -> ConversionResult:
    config = load_pipeline_config()
    if not config.input_path.is_file():
        raise FileNotFoundError(f"Input XES file not found: {config.input_path}")
    result = convert_xes_to_prov_kg(config.input_path, config.knowledge_graph_path)
    print(
        f"Wrote {result.stats.triple_count} triples from "
        f"{result.stats.trace_count} traces to {result.output_path}"
    )
    return result


def _count_xes_lines(path: Path) -> int:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def _warn(message: str, stats: ConversionStats | None = None) -> None:
    print(f"Warning: {message}")
    if stats is not None:
        stats.warning_count += 1


def _iter_traces(
    path: Path,
    stats: ConversionStats,
) -> Iterator[tuple[str, str, dict, list, int]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            if _tag(elem) != "trace":
                continue
            attrs = _attrs(elem, stats)
            trace_id = _get(attrs, CASE_ID_KEY)
            if not trace_id:
                _warn(f"Skipping trace without '{CASE_ID_KEY}' attribute.", stats)
                stats.skipped_traces += 1
                elem.clear()
                continue

            name = _get(attrs, CASE_NAME_KEY)
            if not name:
                _warn(
                    f"Trace '{trace_id}' has no '{CASE_NAME_KEY}'; "
                    f"using case id as label.",
                    stats,
                )
                name = trace_id

            events = []
            skipped = 0
            for child in elem.findall("event"):
                event = _parse_event(child, trace_id, stats)
                if event:
                    events.append(event)
                else:
                    skipped += 1

            if not events:
                _warn(f"Trace '{trace_id}' has no usable events.", stats)

            events.sort(key=lambda item: item[2] or "")
            yield (trace_id, name, attrs, events, skipped)
            elem.clear()


def _parse_event(
    elem: ET.Element,
    trace_id: str,
    stats: ConversionStats,
) -> tuple | None:
    attrs = _attrs(elem, stats)
    event_id = _get(attrs, EVENT_ID_KEY)
    activity_name = _get(attrs, ACTIVITY_KEY)

    if not event_id:
        _warn(f"Trace '{trace_id}': skipping event without '{EVENT_ID_KEY}'.", stats)
        return None
    if not activity_name:
        _warn(
            f"Trace '{trace_id}': skipping event '{event_id}' "
            f"without '{ACTIVITY_KEY}'.",
            stats,
        )
        return None

    timestamp = _get(attrs, TIMESTAMP_KEY)
    if not timestamp:
        _warn(
            f"Trace '{trace_id}', event '{event_id}': missing '{TIMESTAMP_KEY}'.",
            stats,
        )

    resource = _get(attrs, RESOURCE_KEY)
    if not resource:
        _warn(
            f"Trace '{trace_id}', event '{event_id}': missing '{RESOURCE_KEY}'.",
            stats,
        )

    role = _get(attrs, ROLE_KEY)
    if not role:
        _warn(
            f"Trace '{trace_id}', event '{event_id}': missing '{ROLE_KEY}'.",
            stats,
        )

    return (event_id, activity_name, timestamp or "", resource or "", role or "", attrs)


def _emit_trace(
    graph: Graph,
    trace_id: str,
    name: str,
    attrs: dict,
    events: list,
    agents_seen: set[str],
    stats: ConversionStats,
) -> int:
    start = len(graph)
    case = _uri("case", trace_id)

    graph.add((case, RDF.type, PROV.Entity))
    graph.add((case, RDFS.label, Literal(name)))
    _copy_attrs(graph, case, attrs, stats)
    graph.add((case, _attr(CASE_ID_KEY), Literal(trace_id)))

    prev = None
    for event_id, activity_name, timestamp, resource, role, eattrs in events:
        activity = _uri("activity", event_id)

        graph.add((activity, RDF.type, PROV.Activity))
        graph.add((activity, RDFS.label, Literal(activity_name)))
        _copy_attrs(graph, activity, eattrs, stats)
        graph.add((activity, _attr(EVENT_ID_KEY), Literal(event_id)))

        if timestamp:
            ts = _datetime(timestamp, stats)
            graph.add((activity, PROV.startedAtTime, ts))
            graph.add((activity, PROV.endedAtTime, ts))

        if resource:
            agent = _uri("agent", resource)
            if str(agent) not in agents_seen:
                agents_seen.add(str(agent))
                graph.add((agent, RDF.type, PROV.Agent))
                graph.add((agent, RDFS.label, Literal(resource)))
                graph.add((agent, _attr(RESOURCE_KEY), Literal(resource)))
                if role:
                    graph.add((agent, _attr(ROLE_KEY), Literal(role)))
            elif role:
                role_pred = _attr(ROLE_KEY)
                if Literal(role) not in set(graph.objects(agent, role_pred)):
                    graph.add((agent, role_pred, Literal(role)))
                    _warn(
                        f"Agent '{resource}' already exists; "
                        f"adding additional role '{role}'.",
                        stats,
                    )
            graph.add((activity, PROV.wasAssociatedWith, agent))
        else:
            _warn(
                f"Activity '{event_id}' has no resource; "
                "omitting prov:wasAssociatedWith.",
                stats,
            )

        graph.add((activity, WF.belongsToCase, case))
        graph.add((activity, PROV.used, case))
        if prev is None:
            graph.add((case, PROV.wasGeneratedBy, activity))
        else:
            graph.add((activity, PROV.wasInformedBy, prev))
        prev = activity

    return len(graph) - start


def _attrs(elem: ET.Element, stats: ConversionStats) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for child in elem:
        key = child.get("key")
        if not key:
            continue
        value_type = _tag(child)
        if value_type not in VALUE_TYPES:
            _warn(
                f"Unknown XES value type '{value_type}' for key '{key}'; "
                "treating as string.",
                stats,
            )
            value_type = "string"
        result[key] = (child.get("value", ""), value_type)
    return result


def _get(attrs: dict[str, tuple[str, str]], key: str) -> str | None:
    if key in attrs and attrs[key][0]:
        return attrs[key][0]
    return None


def _copy_attrs(
    graph: Graph,
    subject: URIRef,
    attrs: dict[str, tuple[str, str]],
    stats: ConversionStats,
) -> None:
    for key, (value, value_type) in attrs.items():
        if not value:
            continue
        graph.add((subject, _attr(key), _literal(value, value_type, stats)))


def _attr(key: str) -> URIRef:
    local = f"xes-attr_{key.replace(':', '_').replace(';', '_')}"
    return ATTR[local]


def _literal(value: str, value_type: str, stats: ConversionStats) -> Literal:
    if value_type == "date":
        return _datetime(value, stats)
    if value_type == "int":
        try:
            return Literal(int(value), datatype=XSD.integer)
        except ValueError:
            _warn(f"Invalid int value {value!r}; storing as plain string.", stats)
            return Literal(value)
    if value_type == "float":
        try:
            return Literal(float(value), datatype=XSD.double)
        except ValueError:
            _warn(f"Invalid float value {value!r}; storing as plain string.", stats)
            return Literal(value)
    if value_type == "boolean":
        return Literal(value.lower() in {"true", "1", "yes"}, datatype=XSD.boolean)
    return Literal(value)


def _datetime(value: str, stats: ConversionStats) -> Literal:
    try:
        return Literal(
            datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat(),
            datatype=XSD.dateTime,
        )
    except ValueError:
        _warn(f"Invalid datetime value {value!r}; storing as xsd:string.", stats)
        return Literal(value, datatype=XSD.string)


def _uri(kind: str, value: str) -> URIRef:
    return URIRef(f"{BASE}{kind}/{quote(value.strip().replace(' ', '_'), safe='')}")


def _bind(graph: Graph) -> None:
    graph.bind("prov", PROV)
    graph.bind("attr", ATTR)
    graph.bind("wf", WF)
    graph.bind("rdfs", RDFS)


def _tag(elem: ET.Element) -> str:
    return elem.tag.rsplit("}", 1)[-1]


def main() -> None:
    run_from_config()


if __name__ == "__main__":
    main()
