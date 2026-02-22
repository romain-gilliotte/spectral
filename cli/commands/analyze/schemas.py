"""Schema inference utilities.

All four parts of an endpoint (path params, query params, request body,
response body) use the same annotated JSON-schema format produced by
``infer_schema``.  The ``infer_path_schema`` and ``infer_query_schema``
helpers build schemas from trace URLs so that all four are uniform.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from cli.commands.capture.types import Trace
import cli.helpers.llm as llm

# (name, regex, min_keys) — high-confidence patterns (uuid, hex) need only 1 key;
# ambiguous patterns (date, year, numeric) need 3 to avoid false positives.
_DYNAMIC_KEY_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    ("date", re.compile(r"^\d{4}-\d{2}-\d{2}"), 3),
    ("year-month", re.compile(r"^\d{4}-\d{2}$"), 3),
    ("uuid", re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I), 1),
    ("prefixed-uuid", re.compile(r"^.+-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I), 1),
    ("year", re.compile(r"^(?:19|20)\d{2}$"), 3),
    ("numeric-id", re.compile(r"^\d+$"), 3),
    ("hex-id", re.compile(r"^[0-9a-f]{20,}$", re.I), 1),
]

_MIN_STRUCTURAL_KEYS = 5


def _classify_key_pattern(keys: list[str]) -> str | None:
    """Return the pattern name if ALL *keys* match a single dynamic pattern.

    Each pattern carries its own minimum key count.  High-confidence patterns
    (UUID, hex hash) trigger with a single key; ambiguous patterns (date,
    numeric) require at least 3.  Returns ``None`` when no pattern matches.
    """
    for name, regex, min_keys in _DYNAMIC_KEY_PATTERNS:
        if len(keys) >= min_keys and all(regex.search(k) for k in keys):
            return name
    return None


def _schemas_structurally_similar(value_dicts: list[dict[str, Any]]) -> bool:
    """Return True when all *value_dicts* are objects with >50% property overlap.

    Each element must be a ``dict`` with at least one key.  Overlap is measured
    via the Jaccard index: ``|intersection| / |union|`` of the property-name
    sets across all dicts.
    """
    if not value_dicts:
        return False
    sets = [set(d.keys()) for d in value_dicts]
    intersection = sets[0]
    union = sets[0]
    for s in sets[1:]:
        intersection = intersection & s
        union = union | s
    if not union:
        return False
    return len(intersection) / len(union) > 0.5


def _infer_type(value: Any) -> str:
    """Infer JSON schema type from a Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _infer_type_from_values(values: list[str]) -> str:
    """Infer type from a list of string values."""
    if all(v.isdigit() for v in values if v):
        return "integer"
    if all(_is_float(v) for v in values if v):
        return "number"
    if all(v.lower() in ("true", "false") for v in values if v):
        return "boolean"
    return "string"


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _detect_format(values: list[Any]) -> str | None:
    """Detect common string formats."""
    str_values = [v for v in values if isinstance(v, str)]
    if not str_values:
        return None

    if all(re.match(r"^\d{4}-\d{2}-\d{2}", v) for v in str_values):
        return "date-time" if any("T" in v for v in str_values) else "date"

    if all(re.match(r"^[^@]+@[^@]+\.[^@]+$", v) for v in str_values):
        return "email"

    if all(
        re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", v, re.I
        )
        for v in str_values
    ):
        return "uuid"

    if all(re.match(r"^https?://", v) for v in str_values):
        return "uri"

    return None


def _collect_observed(values: list[Any], max_count: int = 5) -> list[Any]:
    """Collect up to *max_count* distinct observed values."""
    seen: list[Any] = []
    seen_set: set[str | int | float | bool | None] = set()
    for v in values:
        try:
            hashable: str | int | float | bool | None = (
                v if not isinstance(v, (dict, list)) else str(v)  # pyright: ignore[reportUnknownArgumentType]
            )
            if hashable not in seen_set:
                seen_set.add(hashable)
                seen.append(v)
                if len(seen) >= max_count:
                    break
        except TypeError:
            seen.append(v)
            if len(seen) >= max_count:
                break
    return seen


def infer_schema(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer a JSON schema from multiple object samples, annotated with observed values.

    Recursively explores nested objects and arrays of objects so that the
    resulting schema fully describes the structure at every level.

    Each property carries its type, optional format, and an "observed" list of up
    to 5 distinct values seen across samples.

    Returns a dict like:
    {
        "type": "object",
        "properties": {
            "status": {"type": "string", "observed": ["active", "inactive"]},
            "count": {"type": "integer", "observed": [1, 5, 10]},
            "address": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "observed": ["Paris"]}
                }
            }
        }
    }
    """
    return _infer_object_schema(samples)


def _infer_object_schema(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer schema for a list of object samples (recursive)."""
    all_keys: dict[str, list[Any]] = defaultdict(list)
    for sample in samples:
        for key, value in sample.items():
            all_keys[key].append(value)

    # Check for dynamic map keys (dates, years, UUIDs, numeric IDs).
    pattern = _classify_key_pattern(list(all_keys.keys()))
    if pattern is not None:
        # Verify value type uniformity (all non-null values share the same type).
        all_values: list[Any] = []
        for vals in all_keys.values():
            all_values.extend(vals)
        non_null_values = [v for v in all_values if v is not None]
        if non_null_values:
            types = {_infer_type(v) for v in non_null_values}
            if len(types) == 1:
                value_schema = _infer_property(all_values)
                sample_keys = list(all_keys.keys())[:5]
                return {
                    "type": "object",
                    "additionalProperties": value_schema,
                    "x-key-pattern": pattern,
                    "x-key-examples": sample_keys,
                }

    properties: dict[str, Any] = {}
    for key, values in all_keys.items():
        properties[key] = _infer_property(values)

    schema: dict[str, Any] = {"type": "object", "properties": properties}

    if pattern is None:
        candidate = _detect_map_candidate(all_keys)
        if candidate is not None:
            schema["x-map-candidate"] = candidate

    return schema


def _detect_map_candidate(
    all_keys: dict[str, list[Any]],
) -> dict[str, Any] | None:
    """Detect a structural map candidate when regex-based detection missed.

    Returns an ``x-map-candidate`` annotation dict when the object has
    ``_MIN_STRUCTURAL_KEYS`` or more keys whose non-null values are all
    dicts with >50% property overlap.  Returns ``None`` otherwise.
    """
    keys = list(all_keys.keys())
    if len(keys) < _MIN_STRUCTURAL_KEYS:
        return None

    value_dicts: list[dict[str, Any]] = []
    for vals in all_keys.values():
        non_null: list[Any] = [v for v in vals if v is not None]
        if not non_null or not all(isinstance(v, dict) and v for v in non_null):  # pyright: ignore[reportUnknownArgumentType]
            return None
        value_dicts.extend(v for v in non_null if isinstance(v, dict))  # pyright: ignore[reportUnknownArgumentType]

    if not value_dicts or not _schemas_structurally_similar(value_dicts):
        return None

    sets = [set(d.keys()) for d in value_dicts]
    intersection = sets[0]
    union = sets[0]
    for s in sets[1:]:
        intersection = intersection & s
        union = union | s

    return {
        "keys": keys[:10],
        "shared_properties": sorted(intersection),
        "extra_properties": sorted(union - intersection),
    }


def _infer_property(values: list[Any]) -> dict[str, Any]:
    """Infer schema for a single property from its observed values."""
    # Skip None values when determining the type so that a leading null
    # doesn't shadow the real type (e.g. [None, {"lon": 4.8}] → object).
    non_null = [v for v in values if v is not None]
    representative = non_null[0] if non_null else None
    prop_type = _infer_type(representative)
    prop: dict[str, Any] = {"type": prop_type}

    if prop_type == "string" and non_null:
        fmt = _detect_format(non_null)
        if fmt:
            prop["format"] = fmt

    if prop_type == "object":
        # Recurse into nested objects
        dict_values: list[dict[str, Any]] = [v for v in non_null if isinstance(v, dict)]
        if dict_values:
            nested = _infer_object_schema(dict_values)
            for k, v in nested.items():
                if k != "type":
                    prop[k] = v

    if prop_type == "array":
        # Infer items schema from array contents — observed goes on items, not here
        items_schema = _infer_array_items(non_null)
        if items_schema:
            prop["items"] = items_schema
        return prop

    prop["observed"] = _collect_observed(values)
    return prop


def _infer_array_items(array_values: list[Any]) -> dict[str, Any] | None:
    """Infer the items schema for an array property.

    Collects all elements from all observed arrays and infers a unified schema.
    """
    all_elements: list[Any] = []
    for v in array_values:
        if isinstance(v, list):
            all_elements.extend(v)  # pyright: ignore[reportUnknownArgumentType]

    if not all_elements:
        return None

    # If all elements are objects, recurse
    dict_elements: list[dict[str, Any]] = [e for e in all_elements if isinstance(e, dict)]
    if dict_elements and len(dict_elements) == len(all_elements):
        return _infer_object_schema(dict_elements)

    # Otherwise infer a scalar type from the first element
    item_type = _infer_type(all_elements[0])
    schema: dict[str, Any] = {"type": item_type}
    if item_type == "string":
        fmt = _detect_format(all_elements)
        if fmt:
            schema["format"] = fmt
    schema["observed"] = _collect_observed(all_elements)
    return schema


def _extract_path_param_values(
    traces: list[Trace],
    path_pattern: str,
    param_names: list[str],
) -> dict[str, list[str]]:
    """Extract observed path parameter values from trace URLs.

    Builds a named-group regex from the pattern and matches each trace URL
    to collect distinct values per parameter.
    """
    regex = path_pattern
    for name in param_names:
        regex = regex.replace(f"{{{name}}}", f"(?P<{name}>[^/]+)")
    regex = regex + "$"
    compiled = re.compile(regex)

    result: dict[str, list[str]] = {name: [] for name in param_names}
    seen: dict[str, set[str]] = {name: set() for name in param_names}
    for t in traces:
        parsed = urlparse(t.meta.request.url)
        m = compiled.search(parsed.path)
        if m:
            for name in param_names:
                val = m.group(name)
                if val and val not in seen[name]:
                    seen[name].add(val)
                    result[name].append(val)
    return result


def infer_path_schema(
    traces: list[Trace], path_pattern: str
) -> dict[str, Any] | None:
    """Infer an annotated JSON schema for path parameters.

    Extracts parameter values from trace URLs using the path pattern, then
    builds a schema in the same format as ``infer_schema``: an object with
    one property per path parameter, each carrying type, optional format,
    and observed values.  All path parameters are required.

    Returns ``None`` when the pattern contains no ``{param}`` segments.
    """
    param_names = re.findall(r"\{(\w+)\}", path_pattern)
    if not param_names:
        return None

    observed = _extract_path_param_values(traces, path_pattern, param_names)

    properties: dict[str, Any] = {}
    for name in param_names:
        values = observed.get(name, [])
        ptype = _infer_type_from_values(values) if values else "string"
        prop: dict[str, Any] = {"type": ptype}
        if ptype == "string" and values:
            fmt = _detect_format(values)
            if fmt:
                prop["format"] = fmt
        prop["observed"] = _collect_observed(values)
        properties[name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": list(param_names),
    }


def infer_query_schema(traces: list[Trace]) -> dict[str, Any] | None:
    """Infer an annotated JSON schema for query string parameters.

    Collects query-string values across all *traces*, infers type and
    format per parameter.  Returns the same annotated-schema format as
    ``infer_schema``.

    Returns ``None`` when no query parameters are found.
    """
    raw_params: dict[str, list[str]] = defaultdict(list)
    for trace in traces:
        parsed = urlparse(trace.meta.request.url)
        qs = parse_qs(parsed.query)
        for key, values in qs.items():
            raw_params[key].extend(values)

    if not raw_params:
        return None

    properties: dict[str, Any] = {}
    for name, values in raw_params.items():
        ptype = _infer_type_from_values(values)
        prop: dict[str, Any] = {"type": ptype}
        if ptype == "string" and values:
            fmt = _detect_format(values)
            if fmt:
                prop["format"] = fmt
        prop["observed"] = _collect_observed(values)
        properties[name] = prop

    return {"type": "object", "properties": properties}


# ---------------------------------------------------------------------------
# LLM-based map candidate resolution
# ---------------------------------------------------------------------------


def _collect_map_candidates(
    schema: dict[str, Any], path: str = ""
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Walk *schema* recursively, returning ``(path, parent, candidate)`` tuples.

    Each tuple contains the dotted path to the annotated node, a reference to
    the node itself (so it can be mutated in-place), and the ``x-map-candidate``
    dict.
    """
    results: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    candidate: dict[str, Any] | None = schema.get("x-map-candidate")  # pyright: ignore[reportAssignmentType]
    if isinstance(candidate, dict):
        results.append((path or "(root)", schema, candidate))

    # Recurse into properties
    for key, prop in schema.get("properties", {}).items():
        if isinstance(prop, dict):
            child_path = f"{path}.{key}" if path else key
            results.extend(_collect_map_candidates(cast(dict[str, Any], prop), child_path))

    # Recurse into additionalProperties
    addl: dict[str, Any] | None = schema.get("additionalProperties")  # pyright: ignore[reportAssignmentType]
    if isinstance(addl, dict):
        child_path = f"{path}[*]" if path else "[*]"
        results.extend(_collect_map_candidates(addl, child_path))

    # Recurse into array items
    items_val: dict[str, Any] | None = schema.get("items")  # pyright: ignore[reportAssignmentType]
    if isinstance(items_val, dict):
        child_path = f"{path}[]" if path else "[]"
        results.extend(_collect_map_candidates(items_val, child_path))

    return results


async def resolve_map_candidates(schemas: list[dict[str, Any]]) -> None:
    """Resolve ``x-map-candidate`` annotations via one batched LLM call.

    Walks all *schemas* (mutating them in-place), collects every
    ``x-map-candidate`` annotation, and asks the LLM whether each group of
    keys represents a dynamic map or fixed properties.  Confirmed maps are
    collapsed to ``additionalProperties``; denied candidates keep their
    ``properties`` unchanged.

    Skips the LLM call entirely when no candidates are found.
    """
    all_candidates: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for schema in schemas:
        all_candidates.extend(_collect_map_candidates(schema))

    if not all_candidates:
        return

    # Build a compact prompt with one group per candidate.
    groups: list[str] = []
    for i, (_path, _node, candidate) in enumerate(all_candidates, 1):
        keys_str = ", ".join(f'"{k}"' for k in candidate["keys"])
        shared_str = ", ".join(candidate["shared_properties"])
        extra_str = ", ".join(candidate["extra_properties"]) or "(none)"
        groups.append(
            f"Group {i}:\n"
            f"  keys: [{keys_str}]\n"
            f"  shared properties: [{shared_str}]\n"
            f"  extra properties: [{extra_str}]"
        )

    prompt = (
        "For each group below, determine whether the keys are dynamic IDs "
        "(a map/dictionary where each key is a unique identifier) or fixed "
        "property names.\n\n"
        + "\n\n".join(groups)
        + "\n\nRespond as a JSON array: "
        '[{"group": 1, "is_map": true}, ...]'
    )

    raw = await llm.ask(prompt, label="resolve-map-candidates")
    parsed = llm.extract_json(raw)
    decisions: list[dict[str, Any]] = parsed if isinstance(parsed, list) else [parsed]

    decision_map: dict[int, bool] = {}
    for d in decisions:
        gnum = d.get("group")
        is_map = d.get("is_map")
        if isinstance(gnum, int) and isinstance(is_map, bool):
            decision_map[gnum] = is_map

    for i, (_path, node, candidate) in enumerate(all_candidates, 1):
        is_map = decision_map.get(i)
        if is_map is True:
            # Collapse properties into additionalProperties.
            props = node.get("properties", {})
            all_values: list[Any] = []
            for prop_schema in props.values():
                all_values.append(prop_schema)
            value_schema = _merge_property_schemas(all_values) if all_values else {}
            node.pop("properties", None)
            node["additionalProperties"] = value_schema
            node["x-key-pattern"] = "dynamic"
            node["x-key-examples"] = candidate["keys"][:5]
        # Always remove the temporary annotation.
        node.pop("x-map-candidate", None)


def _merge_property_schemas(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge multiple property schemas (from different map values) into one.

    Collects all nested ``properties`` into a union and delegates to
    ``_infer_property`` for each.  Falls back to the first schema if the
    inputs are not objects.
    """
    # If any schema has "properties", merge them as objects.
    all_have_props = all("properties" in s for s in schemas)
    if all_have_props:
        merged_keys: dict[str, list[Any]] = defaultdict(list)
        for s in schemas:
            for key, prop in s.get("properties", {}).items():
                merged_keys[key].append(prop)
        merged_props: dict[str, Any] = {}
        for key, prop_list in merged_keys.items():
            # Use the first schema as representative (they share structure).
            merged_props[key] = prop_list[0]
        result: dict[str, Any] = {"type": "object", "properties": merged_props}
        # Carry over observed if present on any input.
        for s in schemas:
            if "observed" in s:
                result["observed"] = s["observed"]
                break
        return result
    return schemas[0] if schemas else {}
