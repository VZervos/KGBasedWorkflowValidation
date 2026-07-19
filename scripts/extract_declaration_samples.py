"""Extract sample XES files with N full declaration traces."""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "dataset" / "DomesticDeclarations.xes.gz"
OUT_DIR = Path(__file__).resolve().parent.parent / "dataset"
TARGETS = (1, 5)


def _tag(elem: ET.Element) -> str:
    return elem.tag.rsplit("}", 1)[-1]


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _dump_attr(child: ET.Element, level: int) -> str:
    pad = "\t" * level
    attrs = "".join(f' {key}="{_esc(val)}"' for key, val in child.attrib.items())
    return f"{pad}<{_tag(child)}{attrs}/>"


def _dump_event(event: ET.Element, level: int) -> list[str]:
    pad = "\t" * level
    lines = [f"{pad}<event>"]
    for child in event:
        if _tag(child) in {"string", "date", "int", "float", "boolean"}:
            lines.append(_dump_attr(child, level + 1))
    lines.append(f"{pad}</event>")
    return lines


def _dump_trace(trace: ET.Element, level: int = 1) -> list[str]:
    pad = "\t" * level
    lines = [f"{pad}<trace>"]
    for child in trace:
        kind = _tag(child)
        if kind == "event":
            lines.extend(_dump_event(child, level + 1))
        elif kind in {"string", "date", "int", "float", "boolean"}:
            lines.append(_dump_attr(child, level + 1))
    lines.append(f"{pad}</trace>")
    return lines


def _trace_id(trace: ET.Element) -> str:
    for child in trace:
        if _tag(child) in {"string", "date", "int", "float", "boolean"} and child.get("key") == "id":
            return child.get("value", "")
    return "(unknown)"


def _event_count(trace: ET.Element) -> int:
    return sum(1 for child in trace if _tag(child) == "event")


def _write_sample(n_declarations: int, traces: list[ET.Element], path: Path) -> None:
    label = "declaration" if n_declarations == 1 else "declarations"
    lines = [
        '<?xml version="1.0" encoding="UTF-8" ?>',
        (
            f"<!-- Sample with {n_declarations} full {label} "
            "extracted from DomesticDeclarations.xes.gz -->"
        ),
        '<log xes.version="1.0" xes.features="nested-attributes" openxes.version="1.0RC7">',
        '\t<extension name="Organizational" prefix="org" uri="http://www.xes-standard.org/org.xesext"/>',
        '\t<extension name="Time" prefix="time" uri="http://www.xes-standard.org/time.xesext"/>',
        '\t<extension name="Concept" prefix="concept" uri="http://www.xes-standard.org/concept.xesext"/>',
        '\t<string key="concept:name" value="Domestic Declarations"/>',
    ]
    for trace in traces:
        lines.extend(_dump_trace(trace))
    lines.append("</log>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    needed = max(TARGETS)
    traces: list[ET.Element] = []

    with gzip.open(SRC, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            if _tag(elem) != "trace":
                continue
            traces.append(deepcopy(elem))
            elem.clear()
            if len(traces) >= needed:
                break

    if len(traces) < needed:
        raise SystemExit(f"Only found {len(traces)} traces, need at least {needed}")

    for n_declarations in TARGETS:
        selected = traces[:n_declarations]
        path = OUT_DIR / (
            f"DomesticDeclarations.sample_{n_declarations}"
            f"{'declaration' if n_declarations == 1 else 'declarations'}.xes"
        )
        _write_sample(n_declarations, selected, path)
        print(f"Wrote {path}")
        for index, trace in enumerate(selected, start=1):
            print(
                f"  {index}. {_trace_id(trace)} "
                f"({_event_count(trace)} events)"
            )


if __name__ == "__main__":
    main()
