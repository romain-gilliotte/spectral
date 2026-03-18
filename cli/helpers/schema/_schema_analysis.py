"""Schema analysis: detect dynamic-key maps and resolve via LLM.

Builds on :func:`infer_schema` by post-processing the inferred schema tree
to detect objects whose property names are actually dynamic keys (UUIDs,
dates, numeric IDs, etc.) and collapsing them into ``additionalProperties``.
Ambiguous cases are resolved via a batched LLM call.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, cast

from pydantic import BaseModel

import cli.helpers.llm as llm
from cli.helpers.prompt import render as render_prompt
from cli.helpers.schema._schema_inference import infer_schema


class MapDecision(BaseModel):
    group: int
    is_map: bool


class MapDecisionListResponse(BaseModel):
    items: list[MapDecision]

# ---------------------------------------------------------------------------
# Dynamic key pattern detection (regex-based, deterministic)
# ---------------------------------------------------------------------------

# (name, regex, min_keys) — high-confidence patterns (uuid, hex) need only 1 key;
# ambiguous patterns (date, year, numeric) need 3 to avoid false positives.
_DYNAMIC_KEY_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    ("date", re.compile(r"^\d{4}-\d{2}-\d{2}"), 3),
    ("year-month", re.compile(r"^\d{4}-\d{2}$"), 3),
    (
        "uuid",
        re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
        ),
        1,
    ),
    (
        "prefixed-uuid",
        re.compile(
            r"^.+-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
        ),
        1,
    ),
    ("year", re.compile(r"^(?:19|20)\d{2}$"), 3),
    ("numeric-id", re.compile(r"^\d+$"), 3),
    ("hex-id", re.compile(r"^[0-9a-f]{20,}$", re.I), 1),
]

_MIN_STRUCTURAL_KEYS = 5


def _classify_key_pattern(keys: list[str]) -> str | None:
    """Return the pattern name if ALL *keys* match a single dynamic pattern."""
    for name, regex, min_keys in _DYNAMIC_KEY_PATTERNS:
        if len(keys) >= min_keys and all(regex.search(k) for k in keys):
            return name
    return None


# ---------------------------------------------------------------------------
# Post-hoc regex map detection (walks an already-inferred schema)
# ---------------------------------------------------------------------------


def _detect_regex_maps(schema: dict[str, Any]) -> None:
    """Walk *schema* in-place, collapsing regex-detected dynamic keys.

    At each object node, checks whether the property names match a known
    dynamic-key pattern (UUID, date, year, etc.).  When they do and all
    property schemas share the same type, the node is collapsed from
    ``properties`` to ``additionalProperties``.
    """
    props: dict[str, Any] | None = schema.get("properties")
    if not isinstance(props, dict) or not props:
        # Recurse into additionalProperties / items even if this node has none.
        _recurse_detect_regex_maps(schema)
        return

    props_typed = cast(dict[str, dict[str, Any]], props)
    keys = list(props_typed.keys())
    pattern = _classify_key_pattern(keys)
    if pattern is not None:
        # Check value-type uniformity across all property schemas.
        prop_types = {p.get("type") for p in props_typed.values()}
        if len(prop_types) == 1:
            value_schema = _merge_property_schemas(list(props_typed.values()))
            schema.pop("properties")
            schema["additionalProperties"] = value_schema
            schema["x-key-pattern"] = pattern
            schema["x-key-examples"] = keys[:5]
            _recurse_detect_regex_maps(schema)
            return

    # No collapse — recurse into each property.
    for prop in props_typed.values():
        _detect_regex_maps(prop)

    _recurse_detect_regex_maps(schema)


def _recurse_detect_regex_maps(schema: dict[str, Any]) -> None:
    """Recurse into additionalProperties and array items."""
    addl: dict[str, Any] | None = schema.get("additionalProperties")
    if isinstance(addl, dict):
        _detect_regex_maps(addl)
    items: dict[str, Any] | None = schema.get("items")
    if isinstance(items, dict):
        _detect_regex_maps(items)


# ---------------------------------------------------------------------------
# Structural map candidate detection (walks an already-inferred schema)
# ---------------------------------------------------------------------------


def _schemas_structurally_similar(schemas: list[dict[str, Any]]) -> bool:
    """Return True when all *schemas* are objects with >50% property overlap."""
    if not schemas:
        return False
    sets = [set(s.get("properties", {}).keys()) for s in schemas]
    if not all(sets):
        return False
    intersection = sets[0]
    union = sets[0]
    for s in sets[1:]:
        intersection = intersection & s
        union = union | s
    if not union:
        return False
    return len(intersection) / len(union) > 0.5


def _detect_structural_maps(schema: dict[str, Any]) -> None:
    """Walk *schema* in-place, annotating structural map candidates.

    An object node with ``_MIN_STRUCTURAL_KEYS`` or more properties, all of
    which are object-typed schemas with >50% key overlap, gets an
    ``x-map-candidate`` annotation for later LLM resolution.
    """
    props_raw: dict[str, Any] | None = schema.get("properties")
    if isinstance(props_raw, dict) and props_raw:
        props_typed = cast(dict[str, dict[str, Any]], props_raw)
        keys = list(props_typed.keys())
        if len(keys) >= _MIN_STRUCTURAL_KEYS:
            obj_props = [
                p for p in props_typed.values()
                if p.get("type") == "object"
            ]
            if len(obj_props) == len(keys) and _schemas_structurally_similar(obj_props):
                prop_key_sets = [set(cast(dict[str, Any], p.get("properties", {})).keys()) for p in obj_props]
                intersection = prop_key_sets[0]
                union = prop_key_sets[0]
                for s in prop_key_sets[1:]:
                    intersection = intersection & s
                    union = union | s
                schema["x-map-candidate"] = {
                    "keys": keys[:10],
                    "shared_properties": sorted(intersection),
                    "extra_properties": sorted(union - intersection),
                }

        # Recurse into each property.
        for prop in props_typed.values():
            _detect_structural_maps(prop)

    # Recurse into additionalProperties / items.
    addl: dict[str, Any] | None = schema.get("additionalProperties")
    if isinstance(addl, dict):
        _detect_structural_maps(addl)
    items: dict[str, Any] | None = schema.get("items")
    if isinstance(items, dict):
        _detect_structural_maps(items)


# ---------------------------------------------------------------------------
# LLM-based resolution of structural map candidates
# ---------------------------------------------------------------------------


def _collect_map_candidates(
    schema: dict[str, Any], path: str = ""
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Walk *schema* recursively, returning ``(path, parent, candidate)`` tuples."""
    results: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    candidate: dict[str, Any] | None = schema.get("x-map-candidate")  # pyright: ignore[reportAssignmentType]
    if isinstance(candidate, dict):
        results.append((path or "(root)", schema, candidate))

    for key, prop in schema.get("properties", {}).items():
        if isinstance(prop, dict):
            child_path = f"{path}.{key}" if path else key
            results.extend(_collect_map_candidates(cast(dict[str, Any], prop), child_path))

    addl: dict[str, Any] | None = schema.get("additionalProperties")  # pyright: ignore[reportAssignmentType]
    if isinstance(addl, dict):
        child_path = f"{path}[*]" if path else "[*]"
        results.extend(_collect_map_candidates(addl, child_path))

    items_val: dict[str, Any] | None = schema.get("items")  # pyright: ignore[reportAssignmentType]
    if isinstance(items_val, dict):
        child_path = f"{path}[]" if path else "[]"
        results.extend(_collect_map_candidates(items_val, child_path))

    return results


def _resolve_map_candidates(schema: dict[str, Any]) -> None:
    """Resolve ``x-map-candidate`` annotations on a single schema via LLM."""
    all_candidates = _collect_map_candidates(schema)
    if not all_candidates:
        return

    candidates = [
        {"keys": candidate["keys"], "shared_properties": candidate["shared_properties"], "extra_properties": candidate["extra_properties"]}
        for _path, _node, candidate in all_candidates
    ]

    prompt = render_prompt("schema-resolve-map-candidates.j2", candidates=candidates)

    conv = llm.Conversation(label="resolve-map-candidates")
    response = conv.ask_json(prompt, MapDecisionListResponse)

    decision_map: dict[int, bool] = {}
    for d in response.items:
        decision_map[d.group] = d.is_map

    for i, (_path, node, candidate) in enumerate(all_candidates, 1):
        is_map = decision_map.get(i)
        if is_map is True:
            props = node.get("properties", {})
            all_values: list[Any] = list(props.values())
            value_schema = _merge_property_schemas(all_values) if all_values else {}
            node.pop("properties", None)
            node["additionalProperties"] = value_schema
            node["x-key-pattern"] = "dynamic"
            node["x-key-examples"] = candidate["keys"][:5]
        node.pop("x-map-candidate", None)


# ---------------------------------------------------------------------------
# Schema merging
# ---------------------------------------------------------------------------


def _merge_property_schemas(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge multiple property schemas (from different map values) into one."""
    all_have_props = all("properties" in s for s in schemas)
    if all_have_props:
        merged_keys: dict[str, list[Any]] = defaultdict(list)
        for s in schemas:
            for key, prop in s.get("properties", {}).items():
                merged_keys[key].append(prop)
        merged_props: dict[str, Any] = {}
        for key, prop_list in merged_keys.items():
            merged_props[key] = prop_list[0]
        return {"type": "object", "properties": merged_props}
    return schemas[0] if schemas else {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_schema(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer a schema from *samples* with full map detection and resolution.

    Calls :func:`infer_schema` for pure structural inference, then:

    1. Detects regex-based dynamic keys (UUIDs, dates, etc.) and collapses
       them to ``additionalProperties`` deterministically.
    2. Detects structural map candidates (5+ same-shape object properties)
       and resolves them via a batched LLM call.

    Returns the fully resolved schema.
    """
    schema = infer_schema(samples)
    _detect_regex_maps(schema)
    _detect_structural_maps(schema)
    _resolve_map_candidates(schema)
    return schema
