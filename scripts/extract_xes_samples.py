"""Extract sample XES files with a target number of events per trace."""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "dataset" / "DomesticDeclarations.xes.gz"
OUT_DIR = Path(__file__).resolve().parent.parent / "dataset"
TARGETS = (5, 10)


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


def _write_sample(n_events: int, trace: ET.Element, path: Path) -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8" ?>',
        f"<!-- Sample with {n_events} activities extracted from DomesticDeclarations.xes.gz -->",
        '<log xes.version="1.0" xes.features="nested-attributes" openxes.version="1.0RC7">',
        '\t<extension name="Organizational" prefix="org" uri="http://www.xes-standard.org/org.xesext"/>',
        '\t<extension name="Time" prefix="time" uri="http://www.xes-standard.org/time.xesext"/>',
        '\t<extension name="Concept" prefix="concept" uri="http://www.xes-standard.org/concept.xesext"/>',
        '\t<string key="concept:name" value="Domestic Declarations"/>',
        "\t<trace>",
    ]
    for child in trace:
        kind = _tag(child)
        if kind == "event":
            lines.extend(_dump_event(child, 2))
        elif kind in {"string", "date", "int", "float", "boolean"}:
            lines.append(_dump_attr(child, 2))
    lines.append("\t</trace>")
    lines.append("</log>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    found: dict[int, ET.Element] = {}
    with gzip.open(SRC, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            if _tag(elem) != "trace":
                continue
            n_events = sum(1 for child in elem if _tag(child) == "event")
            if n_events in TARGETS and n_events not in found:
                found[n_events] = deepcopy(elem)
                print(f"Captured trace with {n_events} events")
            elem.clear()
            if len(found) == len(TARGETS):
                break

    missing = [n for n in TARGETS if n not in found]
    if missing:
        raise SystemExit(f"Could not find traces with event counts: {missing}")

    for n_events, trace in found.items():
        path = OUT_DIR / f"DomesticDeclarations.sample_{n_events}events.xes"
        _write_sample(n_events, trace, path)
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
