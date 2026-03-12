"""Mechanical extraction of endpoint specs from grouped traces."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
import json
import re
from typing import Any, cast
from urllib.parse import urlparse

from cli.commands.capture.types import Trace
from cli.commands.openapi.analyze.types import (
    EndpointGroup,
    EndpointSpec,
    RequestSpec,
    ResponseSpec,
)
from cli.helpers.http import get_header
from cli.helpers.schema import analyze_schema, infer_path_schema, infer_query_schema


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a path pattern like /api/users/{user_id}/orders to a regex."""
    parts = re.split(r"\{[^}]+\}", pattern)
    placeholders = re.findall(r"\{[^}]+\}", pattern)

    regex = ""
    for i, part in enumerate(parts):
        regex += re.escape(part)
        if i < len(placeholders):
            regex += r"[^/]+"

    return re.compile(f"^{regex}$")


async def mechanical_extraction(
    groups: list[EndpointGroup], traces: list[Trace]
) -> list[EndpointSpec]:
    """Build EndpointSpec for each group using only mechanical extraction."""
    endpoints: list[EndpointSpec] = []
    for group in groups:
        group_traces = find_traces_for_group(group, traces)
        endpoint = await _build_endpoint_mechanical(
            group.method, group.pattern, group_traces,
        )
        endpoints.append(endpoint)
    return endpoints


def _match_traces_by_pattern(
    method: str, path_pattern: str, traces: list[Trace]
) -> list[Trace]:
    """Return traces whose method and URL path match *path_pattern*."""
    pattern_re = _pattern_to_regex(path_pattern)
    return [
        t
        for t in traces
        if t.meta.request.method.upper() == method
        and pattern_re.match(urlparse(t.meta.request.url).path)
    ]


def find_traces_for_group(group: EndpointGroup, traces: list[Trace]) -> list[Trace]:
    """Find traces whose URLs are listed in the endpoint group."""
    url_set = set(group.urls)
    matched = [
        t
        for t in traces
        if t.meta.request.url in url_set
        and t.meta.request.method.upper() == group.method
    ]

    matched_set = set(id(t) for t in matched)
    for t in _match_traces_by_pattern(group.method, group.pattern, traces):
        if id(t) not in matched_set:
            matched.append(t)
            matched_set.add(id(t))

    return matched


def _collect_json_bodies(
    traces: list[Trace], get_body: Callable[[Trace], bytes]
) -> list[dict[str, Any]]:
    """Parse JSON bodies from *traces*, returning only ``dict`` results."""
    results: list[dict[str, Any]] = []
    for t in traces:
        body = get_body(t)
        if not body:
            continue
        try:
            data: Any = json.loads(body)
            if isinstance(data, dict):
                results.append(cast(dict[str, Any], data))
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return results


async def _build_endpoint_mechanical(
    method: str,
    path_pattern: str,
    traces: list[Trace],
) -> EndpointSpec:
    """Build an endpoint spec from grouped traces (mechanical only)."""
    endpoint_id = _make_endpoint_id(method, path_pattern)

    request_spec = await _build_request_spec(traces, path_pattern)
    response_specs = await _build_response_specs(traces)

    return EndpointSpec(
        id=endpoint_id,
        path=path_pattern,
        method=method,
        request=request_spec,
        responses=response_specs,
    )


def _make_endpoint_id(method: str, path: str) -> str:
    """Generate a readable endpoint ID from method and path."""
    clean = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", clean)
    return f"{method.lower()}_{clean}" if clean else method.lower()


async def _build_request_spec(traces: list[Trace], path_pattern: str) -> RequestSpec:
    """Build request spec from observed traces using annotated schemas."""
    path_schema = infer_path_schema(traces, path_pattern)
    query_schema = infer_query_schema(traces)

    content_type = None
    for trace in traces:
        ct = get_header(trace.meta.request.headers, "content-type")
        if ct:
            content_type = ct

    body_samples = _collect_json_bodies(traces, lambda t: t.request_body)
    body_schema = await analyze_schema(body_samples) if body_samples else None

    return RequestSpec(
        content_type=content_type,
        path_schema=path_schema,
        query_schema=query_schema,
        body_schema=body_schema,
    )


async def _build_response_specs(traces: list[Trace]) -> list[ResponseSpec]:
    """Build response specs from observed traces, grouped by status code."""
    by_status: dict[int, list[Trace]] = defaultdict(list)
    for t in traces:
        by_status[t.meta.response.status].append(t)

    specs: list[ResponseSpec] = []
    for status, status_traces in sorted(by_status.items()):
        ct = get_header(status_traces[0].meta.response.headers, "content-type")

        schema: dict[str, Any] | None = None
        example_body: Any = None
        for t in status_traces:
            if t.response_body and example_body is None:
                try:
                    example_body = json.loads(t.response_body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        body_samples = _collect_json_bodies(status_traces, lambda t: t.response_body)
        if body_samples:
            schema = await analyze_schema(body_samples)

        specs.append(
            ResponseSpec(
                status=status,
                content_type=ct,
                schema_=schema,
                example_body=example_body,
            )
        )

    return specs


_RATE_LIMIT_HEADERS = [
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "retry-after",
]


def extract_rate_limit(traces: list[Trace]) -> str | None:
    """Extract rate limit info from response headers across all traces."""
    found: dict[str, str] = {}
    for t in traces:
        for header in t.meta.response.headers:
            name_lower = header.name.lower()
            if name_lower in _RATE_LIMIT_HEADERS and name_lower not in found:
                found[name_lower] = header.value

    if not found:
        return None

    parts: list[str] = []
    limit = found.get("x-ratelimit-limit") or found.get("ratelimit-limit")
    remaining = found.get("x-ratelimit-remaining") or found.get("ratelimit-remaining")
    reset = found.get("x-ratelimit-reset") or found.get("ratelimit-reset")
    retry = found.get("retry-after")

    if limit:
        parts.append(f"limit={limit}")
    if remaining:
        parts.append(f"remaining={remaining}")
    if reset:
        parts.append(f"reset={reset}")
    if retry:
        parts.append(f"retry-after={retry}")

    return ", ".join(parts) if parts else None
