"""Schema inference and query parameter extraction utilities."""

from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

from cli.capture.models import Trace


def _infer_type(value) -> str:
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


def _detect_format(values: list) -> str | None:
    """Detect common string formats."""
    str_values = [v for v in values if isinstance(v, str)]
    if not str_values:
        return None

    if all(re.match(r"^\d{4}-\d{2}-\d{2}", v) for v in str_values):
        return "date-time" if any("T" in v for v in str_values) else "date"

    if all(re.match(r"^[^@]+@[^@]+\.[^@]+$", v) for v in str_values):
        return "email"

    if all(
        re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", v, re.I)
        for v in str_values
    ):
        return "uuid"

    if all(re.match(r"^https?://", v) for v in str_values):
        return "uri"

    return None


def _infer_json_schema(samples: list[dict]) -> dict:
    """Infer a JSON schema from multiple object samples."""
    total = len(samples)
    all_keys: dict[str, list] = defaultdict(list)
    for sample in samples:
        for key, value in sample.items():
            all_keys[key].append(value)

    properties = {}
    required = []
    for key, values in all_keys.items():
        prop_type = _infer_type(values[0])
        properties[key] = {"type": prop_type}

        if prop_type == "string" and values:
            fmt = _detect_format(values)
            if fmt:
                properties[key]["format"] = fmt

        if len(values) == total:
            required.append(key)

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _merge_schemas(samples: list[dict]) -> dict[str, dict]:
    """Merge multiple JSON object samples into parameter info."""
    all_keys: dict[str, list] = defaultdict(list)
    total = len(samples)
    for sample in samples:
        for key, value in sample.items():
            all_keys[key].append(value)

    result = {}
    for key, values in all_keys.items():
        result[key] = {
            "type": _infer_type(values[0]),
            "required": len(values) == total,
            "example": values[0],
            "values": values,
        }
    return result


def _build_annotated_schema(samples: list[dict]) -> dict:
    """Build a JSON schema annotated with observed values for each property.

    Like _infer_json_schema but adds an "observed" key per property containing
    up to 5 distinct observed values. This gives the LLM concrete examples to
    reason about parameter semantics (e.g. enum detection, format inference).

    Returns a dict like:
    {
        "type": "object",
        "properties": {
            "status": {"type": "string", "observed": ["active", "inactive"]},
            "count": {"type": "integer", "observed": [1, 5, 10]}
        },
        "required": ["status", "count"]
    }
    """
    total = len(samples)
    all_keys: dict[str, list] = defaultdict(list)
    for sample in samples:
        for key, value in sample.items():
            all_keys[key].append(value)

    properties = {}
    required = []
    for key, values in all_keys.items():
        prop_type = _infer_type(values[0])
        prop: dict = {"type": prop_type}

        if prop_type == "string" and values:
            fmt = _detect_format(values)
            if fmt:
                prop["format"] = fmt

        # Add up to 5 distinct observed values
        seen = []
        seen_set: set = set()
        for v in values:
            try:
                hashable = v if not isinstance(v, (dict, list)) else str(v)
                if hashable not in seen_set:
                    seen_set.add(hashable)
                    seen.append(v)
                    if len(seen) >= 5:
                        break
            except TypeError:
                seen.append(v)
                if len(seen) >= 5:
                    break
        prop["observed"] = seen

        if len(values) == total:
            required.append(key)

        properties[key] = prop

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _extract_query_params(traces: list[Trace]) -> dict[str, list[str]]:
    """Extract query parameters from trace URLs."""
    params: dict[str, list[str]] = defaultdict(list)
    for trace in traces:
        parsed = urlparse(trace.meta.request.url)
        qs = parse_qs(parsed.query)
        for key, values in qs.items():
            params[key].extend(values)
    return dict(params)
