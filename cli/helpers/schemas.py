"""Schema inference utilities.

All four parts of an endpoint (path params, query params, request body,
response body) use the same annotated JSON-schema format produced by
``infer_schema``.  The ``infer_path_schema`` and ``infer_query_schema``
helpers build schemas from trace URLs so that all four are uniform.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from cli.commands.capture.types import Trace
from cli.helpers.json import infer_schema

# Re-export for convenience
__all__ = [
    "infer_schema",
    "infer_path_schema",
    "infer_query_schema",
]


def _coerce_value(s: str) -> Any:
    """Convert a string value to its natural Python type."""
    if s.isdigit():
        return int(s)
    try:
        return float(s)
    except ValueError:
        pass
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    return s


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


def _build_samples(
    observed: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Zip per-param value lists into sample dicts with coerced values.

    Each sample dict maps parameter names to coerced Python values.  The
    number of samples equals the length of the longest value list; shorter
    lists are padded by repeating the last value.
    """
    if not observed:
        return []
    max_len = max(len(vals) for vals in observed.values())
    if max_len == 0:
        return []
    samples: list[dict[str, Any]] = []
    for i in range(max_len):
        sample: dict[str, Any] = {}
        for name, vals in observed.items():
            raw = vals[i] if i < len(vals) else vals[-1]
            sample[name] = _coerce_value(raw)
        samples.append(sample)
    return samples


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
    samples = _build_samples(observed)
    schema = infer_schema(samples) if samples else infer_schema([{name: "" for name in param_names}])
    schema["required"] = list(param_names)
    return schema


def infer_query_schema(traces: list[Trace]) -> dict[str, Any] | None:
    """Infer an annotated JSON schema for query string parameters.

    Collects query-string values across all *traces*, infers type and
    format per parameter.  Returns the same annotated-schema format as
    ``infer_schema``.

    Returns ``None`` when no query parameters are found.
    """
    # Collect raw string values per query parameter across all traces.
    raw_params: dict[str, list[str]] = defaultdict(list)
    for trace in traces:
        parsed = urlparse(trace.meta.request.url)
        qs = parse_qs(parsed.query)
        for key, values in qs.items():
            raw_params[key].extend(values)

    if not raw_params:
        return None

    # Build one sample dict per trace, coercing string values to Python types.
    samples: list[dict[str, Any]] = []
    for trace in traces:
        parsed = urlparse(trace.meta.request.url)
        qs = parse_qs(parsed.query)
        if qs:
            sample: dict[str, Any] = {}
            for key, values in qs.items():
                sample[key] = _coerce_value(values[0])
            samples.append(sample)

    if not samples:
        return None

    return infer_schema(samples)
