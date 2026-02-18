"""Step: Mechanical extraction of endpoint specs from grouped traces."""

from __future__ import annotations

from collections import defaultdict
import json
import re
from typing import Any, cast
from urllib.parse import urlparse

from cli.commands.analyze.schemas import extract_query_params, infer_schema
from cli.commands.analyze.steps.base import MechanicalStep
from cli.commands.analyze.steps.types import Correlation, EndpointGroup, GroupedTraceData
from cli.commands.analyze.utils import get_header, pattern_to_regex
from cli.commands.capture.types import Trace
from cli.formats.api_spec import (
    EndpointSpec,
    ParameterSpec,
    RequestSpec,
    ResponseSpec,
    UiTrigger,
)


class MechanicalExtractionStep(MechanicalStep[GroupedTraceData, list[EndpointSpec]]):
    """Build EndpointSpec for each group using only mechanical extraction."""

    name = "mechanical_extraction"

    async def _execute(self, input: GroupedTraceData) -> list[EndpointSpec]:
        endpoints: list[EndpointSpec] = []
        for group in input.groups:
            group_traces = _find_traces_for_group(group, input.traces)
            endpoint = _build_endpoint_mechanical(
                group.method,
                group.pattern,
                group_traces,
                input.correlations,
            )
            endpoints.append(endpoint)
        return endpoints


def _find_traces_for_group(group: EndpointGroup, traces: list[Trace]) -> list[Trace]:
    """Find traces whose URLs are listed in the endpoint group."""
    url_set = set(group.urls)
    matched = [
        t
        for t in traces
        if t.meta.request.url in url_set
        and t.meta.request.method.upper() == group.method
    ]

    # Also try pattern matching to catch traces the LLM didn't list
    pattern_re = pattern_to_regex(group.pattern)
    for t in traces:
        if t not in matched:
            parsed = urlparse(t.meta.request.url)
            if t.meta.request.method.upper() == group.method and pattern_re.match(
                parsed.path
            ):
                matched.append(t)

    return matched


def _build_endpoint_mechanical(
    method: str,
    path_pattern: str,
    traces: list[Trace],
    correlations: list[Correlation],
) -> EndpointSpec:
    """Build an endpoint spec from grouped traces (mechanical only)."""
    endpoint_id = _make_endpoint_id(method, path_pattern)

    ui_triggers: list[UiTrigger] = []
    for corr in correlations:
        for t in corr.traces:
            if t in traces:
                ui_triggers.append(
                    UiTrigger(
                        action=corr.context.meta.action,
                        element_selector=corr.context.meta.element.selector,
                        element_text=corr.context.meta.element.text,
                        page_url=corr.context.meta.page.url,
                    )
                )
                break

    request_spec = _build_request_spec(traces, path_pattern)
    response_specs = _build_response_specs(traces)

    requires_auth = any(
        get_header(t.meta.request.headers, "authorization") is not None
        or _has_auth_cookie(t)
        for t in traces
    )

    return EndpointSpec(
        id=endpoint_id,
        path=path_pattern,
        method=method,
        ui_triggers=ui_triggers,
        request=request_spec,
        responses=response_specs,
        rate_limit=_extract_rate_limit(traces),
        requires_auth=requires_auth,
        observed_count=len(traces),
        source_trace_refs=[t.meta.id for t in traces],
    )


def _make_endpoint_id(method: str, path: str) -> str:
    """Generate a readable endpoint ID from method and path."""
    clean = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", clean)
    return f"{method.lower()}_{clean}" if clean else method.lower()


def _build_request_spec(traces: list[Trace], path_pattern: str) -> RequestSpec:
    """Build request spec from observed traces."""
    parameters: list[ParameterSpec] = []

    path_params = re.findall(r"\{(\w+)\}", path_pattern)
    for param_name in path_params:
        parameters.append(
            ParameterSpec(
                name=param_name,
                location="path",
                type="string",
                required=True,
            )
        )

    content_type = None
    body_schemas: list[dict[str, Any]] = []
    for trace in traces:
        ct = get_header(trace.meta.request.headers, "content-type")
        if ct:
            content_type = ct
        if trace.request_body:
            try:
                data: Any = json.loads(trace.request_body)
                if isinstance(data, dict):
                    body_schemas.append(cast(dict[str, Any], data))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

    if body_schemas:
        schema = infer_schema(body_schemas)
        required_set = set(schema.get("required", []))
        for key, prop in schema["properties"].items():
            parameters.append(
                ParameterSpec(
                    name=key,
                    location="body",
                    type=str(prop["type"]),
                    format=prop.get("format"),
                    required=key in required_set,
                    example=str(prop["observed"][0]) if prop.get("observed") else None,
                    observed_values=[str(v) for v in prop.get("observed", [])[:5]],
                )
            )

    query_params = extract_query_params(traces)
    for name, info in query_params.items():
        values = info["values"]
        parameters.append(
            ParameterSpec(
                name=name,
                location="query",
                type=info["type"],
                format=info["format"],
                required=info["required"],
                example=values[0] if values else None,
                observed_values=list(set(values))[:5],
            )
        )

    return RequestSpec(content_type=content_type, parameters=parameters)


def _build_response_specs(traces: list[Trace]) -> list[ResponseSpec]:
    """Build response specs from observed traces, grouped by status code."""
    by_status: dict[int, list[Trace]] = defaultdict(list)
    for t in traces:
        by_status[t.meta.response.status].append(t)

    specs: list[ResponseSpec] = []
    for status, status_traces in sorted(by_status.items()):
        ct = get_header(status_traces[0].meta.response.headers, "content-type")

        schema: dict[str, Any] | None = None
        example_body: Any = None
        body_samples: list[dict[str, Any]] = []
        for t in status_traces:
            if t.response_body:
                try:
                    resp_data: Any = json.loads(t.response_body)
                    if example_body is None:
                        example_body = resp_data
                    if isinstance(resp_data, dict):
                        body_samples.append(cast(dict[str, Any], resp_data))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        if body_samples:
            schema = infer_schema(body_samples)
            for prop in schema.get("properties", {}).values():
                prop.pop("observed", None)

        specs.append(
            ResponseSpec(
                status=status,
                content_type=ct,
                schema=schema,
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


def _extract_rate_limit(traces: list[Trace]) -> str | None:
    """Extract rate limit info from response headers across all traces.

    Scans for common rate limit headers and returns a human-readable summary,
    or None if no rate limit headers are found.
    """
    found: dict[str, str] = {}
    for t in traces:
        for header in t.meta.response.headers:
            name_lower = header.name.lower()
            if name_lower in _RATE_LIMIT_HEADERS and name_lower not in found:
                found[name_lower] = header.value

    if not found:
        return None

    parts: list[str] = []
    # Normalize to display-friendly names
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


def _has_auth_cookie(trace: Trace) -> bool:
    """Check if a trace has auth-related cookies."""
    cookie = get_header(trace.meta.request.headers, "cookie")
    if cookie and any(
        name in cookie.lower() for name in ["session", "token", "auth", "jwt"]
    ):
        return True
    return False
