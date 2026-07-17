"""XES mapping profiles: defaults and file discovery."""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path

VALUE_TYPE_TAGS = frozenset({"string", "date", "int", "float", "boolean"})
XES_ATTR_BASE = "http://www.xes-standard.org/attribute/"


def normalize_xes_attr_key(key: str) -> str:
    return key.replace(":", "_").replace(";", "_")


def xes_attr_predicate(key: str) -> str:
    return f"xes-attr_{normalize_xes_attr_key(key)}"


def xes_attr_uri(key: str) -> str:
    return f"{XES_ATTR_BASE}{xes_attr_predicate(key)}"

DEFAULT_CASE_ID_KEYS = ("id", "concept:name", "name")
DEFAULT_CASE_NAME_KEYS = ("concept:name", "name")
DEFAULT_EVENT_ID_KEYS = ("id", "concept:name", "name")
DEFAULT_ACTIVITY_LABEL_KEYS = ("concept:name", "name")
DEFAULT_TIMESTAMP_KEYS = ("time:timestamp", "timestamp")
DEFAULT_AGENT_RESOURCE_KEYS = ("org:resource", "resource")
DEFAULT_AGENT_ROLE_KEYS = ("org:role", "role")
DEFAULT_ORDER_KEYS = ("time:timestamp", "timestamp")

@dataclass(frozen=True)
class XesExtension:
    name: str
    prefix: str
    uri: str


@dataclass(frozen=True)
class XesAttribute:
    key: str
    value: str
    value_type: str


@dataclass(frozen=True)
class MappingProfile:
    case_id_keys: tuple[str, ...] = DEFAULT_CASE_ID_KEYS
    case_name_keys: tuple[str, ...] = DEFAULT_CASE_NAME_KEYS
    event_id_keys: tuple[str, ...] = DEFAULT_EVENT_ID_KEYS
    activity_label_keys: tuple[str, ...] = DEFAULT_ACTIVITY_LABEL_KEYS
    timestamp_keys: tuple[str, ...] = DEFAULT_TIMESTAMP_KEYS
    agent_resource_keys: tuple[str, ...] = DEFAULT_AGENT_RESOURCE_KEYS
    agent_role_keys: tuple[str, ...] = DEFAULT_AGENT_ROLE_KEYS
    order_by_keys: tuple[str, ...] = DEFAULT_ORDER_KEYS
    extensions: tuple[XesExtension, ...] = ()
    value_type_tags: frozenset[str] = VALUE_TYPE_TAGS

    @property
    def trace_structural_keys(self) -> frozenset[str]:
        return frozenset(self.case_id_keys + self.case_name_keys)

    @property
    def event_structural_keys(self) -> frozenset[str]:
        return frozenset(
            self.event_id_keys
            + self.activity_label_keys
            + self.timestamp_keys
            + self.agent_resource_keys
            + self.agent_role_keys
        )


def read_xes_extensions(path: Path) -> tuple[XesExtension, ...]:
    """Read declared XES extensions from the log header."""
    opener = gzip.open if path.suffix == ".gz" else open
    extensions: list[XesExtension] = []

    with opener(path, "rb") as handle:
        for _event, element in ET.iterparse(handle, events=("end",)):
            tag = _tag_name(element)
            if tag == "trace":
                break
            if tag != "extension":
                element.clear()
                continue

            name = element.get("name", "").strip()
            prefix = element.get("prefix", "").strip()
            uri = element.get("uri", "").strip()
            if name and prefix:
                extensions.append(XesExtension(name=name, prefix=prefix, uri=uri))
            element.clear()

    return tuple(extensions)


def build_mapping_profile(
    extensions: tuple[XesExtension, ...],
    overrides: dict[str, tuple[str, ...]] | None = None,
) -> MappingProfile:
    """Build an XES-standard profile and apply optional overrides."""
    profile = MappingProfile(extensions=extensions)
    prefixes = {extension.prefix.lower() for extension in extensions}
    names = {extension.name.lower() for extension in extensions}

    if "concept" in prefixes:
        profile = replace(
            profile,
            case_name_keys=_prepend("concept:name", profile.case_name_keys),
            activity_label_keys=_prepend("concept:name", profile.activity_label_keys),
        )
    if "time" in prefixes:
        profile = replace(
            profile,
            timestamp_keys=_prepend("time:timestamp", profile.timestamp_keys),
            order_by_keys=_prepend("time:timestamp", profile.order_by_keys),
        )
    if "org" in prefixes or "organizational" in names:
        profile = replace(
            profile,
            agent_resource_keys=_prepend("org:resource", profile.agent_resource_keys),
            agent_role_keys=_prepend("org:role", profile.agent_role_keys),
        )
    if "id" in prefixes or "identity" in names:
        profile = replace(
            profile,
            case_id_keys=_prepend("id", profile.case_id_keys),
            event_id_keys=_prepend("id", profile.event_id_keys),
        )

    if overrides:
        profile = replace(profile, **overrides)

    return profile


def resolve_mapping_profile(xes_path: Path) -> MappingProfile:
    """Resolve the effective mapping profile for one XES file."""
    extensions = read_xes_extensions(xes_path)
    return build_mapping_profile(extensions)


def first_value(attributes: dict[str, XesAttribute], keys: tuple[str, ...]) -> str | None:
    """Return the first matching attribute value using fallback keys."""
    for key in keys:
        attribute = attributes.get(key)
        if attribute and attribute.value:
            return attribute.value
    return None


def matched_key(attributes: dict[str, XesAttribute], keys: tuple[str, ...]) -> str | None:
    """Return the first key that exists in the attributes."""
    for key in keys:
        if key in attributes and attributes[key].value:
            return key
    return None


def read_attributes(
    element: ET.Element,
    profile: MappingProfile,
) -> dict[str, XesAttribute]:
    """Read all XES attributes and infer each value type from the XML tag."""
    attributes: dict[str, XesAttribute] = {}
    for child in element:
        key = child.get("key")
        if not key:
            continue
        value_type = _tag_name(child)
        if value_type not in profile.value_type_tags:
            value_type = "string"
        attributes[key] = XesAttribute(
            key=key,
            value=child.get("value", ""),
            value_type=value_type,
        )
    return attributes


def _prepend(key: str, keys: tuple[str, ...]) -> tuple[str, ...]:
    tail = tuple(item for item in keys if item != key)
    return (key, *tail)


def _tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]
