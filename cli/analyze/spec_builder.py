"""Build an enriched API spec from a capture bundle using mechanical analysis."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from cli.analyze.correlator import Correlation, correlate, find_uncorrelated_traces
from cli.analyze.protocol import detect_trace_protocol, detect_ws_protocol
from cli.capture.models import CaptureBundle, Trace, WsConnection
from cli.formats.api_spec import (
    ApiSpec,
    AuthInfo,
    BusinessContext,
    EndpointSpec,
    ParameterSpec,
    Protocols,
    RequestSpec,
    ResponseSpec,
    RestProtocol,
    UiTrigger,
    WebSocketProtocol,
    WsConnectionSpec,
    WsMessageSpec,
)


def build_spec(bundle: CaptureBundle, source_filename: str = "") -> ApiSpec:
    """Build an enriched API spec from a capture bundle (mechanical analysis only)."""
    correlations = correlate(bundle)
    uncorrelated = find_uncorrelated_traces(bundle, correlations)

    # Collect all traces (correlated + uncorrelated)
    all_traces = list(bundle.traces)

    # Group traces by endpoint signature (method + normalized path)
    endpoint_groups = _group_by_endpoint(all_traces)

    # Build endpoint specs
    endpoints: list[EndpointSpec] = []
    for (method, path_pattern), traces in sorted(endpoint_groups.items()):
        endpoint = _build_endpoint(method, path_pattern, traces, correlations)
        endpoints.append(endpoint)

    # Detect base URL
    base_url = _detect_base_url(all_traces)

    # Build WebSocket specs
    ws_specs = _build_ws_specs(bundle.ws_connections)

    # Detect auth
    auth = _detect_auth(all_traces)

    return ApiSpec(
        name=bundle.manifest.app.name + " API" if bundle.manifest.app.name else "Discovered API",
        discovery_date=datetime.now(timezone.utc).isoformat(),
        source_captures=[source_filename] if source_filename else [],
        business_context=BusinessContext(
            domain="",
            description=f"API discovered from {bundle.manifest.app.base_url}",
        ),
        auth=auth,
        protocols=Protocols(
            rest=RestProtocol(base_url=base_url, endpoints=endpoints),
            websocket=ws_specs,
        ),
    )


def _group_by_endpoint(traces: list[Trace]) -> dict[tuple[str, str], list[Trace]]:
    """Group traces by (method, normalized_path_pattern)."""
    groups: dict[tuple[str, str], list[Trace]] = defaultdict(list)
    # First pass: collect all URL paths per method
    method_paths: dict[str, list[tuple[str, Trace]]] = defaultdict(list)
    for trace in traces:
        parsed = urlparse(trace.meta.request.url)
        method = trace.meta.request.method.upper()
        method_paths[method].append((parsed.path, trace))

    # Second pass: detect path parameters and normalize
    for method, path_traces in method_paths.items():
        paths = [pt[0] for pt in path_traces]
        pattern_map = _infer_path_patterns(paths)
        for path, trace in path_traces:
            pattern = pattern_map.get(path, path)
            groups[(method, pattern)].append(trace)

    return dict(groups)


def _infer_path_patterns(paths: list[str]) -> dict[str, str]:
    """Infer path parameter patterns from observed URLs.

    Given ['/users/123/orders', '/users/456/orders'], returns a mapping:
    {'/users/123/orders': '/users/{id}/orders', '/users/456/orders': '/users/{id}/orders'}
    """
    result: dict[str, str] = {}

    # Group paths by their segment count
    by_length: dict[int, list[list[str]]] = defaultdict(list)
    for path in paths:
        segments = path.strip("/").split("/")
        by_length[len(segments)].append(segments)

    for length, segment_lists in by_length.items():
        if length == 0:
            for p in paths:
                if p.strip("/") == "":
                    result[p] = "/"
            continue

        # For each position, check if the segment varies
        varying_positions = set()
        if len(segment_lists) > 1:
            for pos in range(length):
                values = {segs[pos] for segs in segment_lists}
                if len(values) > 1:
                    # Check if all varying values look like IDs
                    if all(_looks_like_id(v) for v in values):
                        varying_positions.add(pos)

        # Build pattern for each path in this group
        for segments in segment_lists:
            original = "/" + "/".join(segments)
            pattern_segments = []
            for pos, seg in enumerate(segments):
                if pos in varying_positions:
                    param_name = _infer_param_name(segments, pos)
                    pattern_segments.append("{" + param_name + "}")
                else:
                    pattern_segments.append(seg)
            result[original] = "/" + "/".join(pattern_segments)

    # Handle paths not yet mapped (single occurrences)
    for path in paths:
        if path not in result:
            result[path] = path

    return result


def _looks_like_id(segment: str) -> bool:
    """Check if a URL segment looks like a dynamic ID."""
    # Numeric
    if segment.isdigit():
        return True
    # UUID-like
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", segment, re.I):
        return True
    # Hex hash-like (8+ chars)
    if re.match(r"^[0-9a-f]{8,}$", segment, re.I) and not segment.isalpha():
        return True
    return False


def _infer_param_name(segments: list[str], pos: int) -> str:
    """Infer a parameter name from context."""
    # Use the preceding segment as a hint (e.g., /users/{id} -> user_id)
    if pos > 0:
        prev = segments[pos - 1].rstrip("s")  # simple de-pluralization
        return f"{prev}_id"
    return "id"


def _build_endpoint(
    method: str,
    path_pattern: str,
    traces: list[Trace],
    correlations: list[Correlation],
) -> EndpointSpec:
    """Build an endpoint spec from grouped traces."""
    endpoint_id = _make_endpoint_id(method, path_pattern)

    # Collect UI triggers from correlations
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
                break  # one trigger per correlation

    # Build request spec
    request_spec = _build_request_spec(traces, path_pattern)

    # Build response specs
    response_specs = _build_response_specs(traces)

    # Detect auth requirement
    requires_auth = any(
        _get_header(t.meta.request.headers, "authorization") is not None
        for t in traces
    )

    return EndpointSpec(
        id=endpoint_id,
        path=path_pattern,
        method=method,
        ui_triggers=ui_triggers,
        request=request_spec,
        responses=response_specs,
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

    # Path parameters
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

    # Infer body parameters from JSON request bodies
    content_type = None
    body_schemas: list[dict] = []
    for trace in traces:
        ct = _get_header(trace.meta.request.headers, "content-type")
        if ct:
            content_type = ct
        if trace.request_body:
            try:
                data = json.loads(trace.request_body)
                if isinstance(data, dict):
                    body_schemas.append(data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

    if body_schemas:
        merged = _merge_schemas(body_schemas)
        for key, info in merged.items():
            parameters.append(
                ParameterSpec(
                    name=key,
                    location="body",
                    type=info["type"],
                    required=info["required"],
                    example=str(info["example"]) if info["example"] is not None else None,
                    observed_values=[str(v) for v in info["values"][:5]],
                )
            )

    # Infer query parameters from URLs
    query_params = _extract_query_params(traces)
    for name, values in query_params.items():
        parameters.append(
            ParameterSpec(
                name=name,
                location="query",
                type=_infer_type_from_values(values),
                required=len(values) == len(traces),
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
        ct = _get_header(status_traces[0].meta.response.headers, "content-type")

        # Try to infer schema from JSON response bodies
        schema = None
        example_body = None
        body_samples: list[dict] = []
        for t in status_traces:
            if t.response_body:
                try:
                    data = json.loads(t.response_body)
                    if example_body is None:
                        example_body = data
                    if isinstance(data, dict):
                        body_samples.append(data)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        if body_samples:
            schema = _infer_json_schema(body_samples)

        specs.append(
            ResponseSpec(
                status=status,
                content_type=ct,
                schema=schema,
                example_body=example_body,
            )
        )

    return specs


def _merge_schemas(samples: list[dict]) -> dict[str, dict]:
    """Merge multiple JSON object samples into parameter info.

    Returns {field_name: {"type": str, "required": bool, "example": Any, "values": list}}
    """
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

        # Detect common formats
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


def _detect_format(values: list) -> str | None:
    """Detect common string formats."""
    str_values = [v for v in values if isinstance(v, str)]
    if not str_values:
        return None

    # ISO date
    if all(re.match(r"^\d{4}-\d{2}-\d{2}", v) for v in str_values):
        return "date-time" if any("T" in v for v in str_values) else "date"

    # Email
    if all(re.match(r"^[^@]+@[^@]+\.[^@]+$", v) for v in str_values):
        return "email"

    # UUID
    if all(
        re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", v, re.I)
        for v in str_values
    ):
        return "uuid"

    # URL
    if all(re.match(r"^https?://", v) for v in str_values):
        return "uri"

    return None


def _extract_query_params(traces: list[Trace]) -> dict[str, list[str]]:
    """Extract query parameters from trace URLs."""
    from urllib.parse import parse_qs, urlparse

    params: dict[str, list[str]] = defaultdict(list)
    for trace in traces:
        parsed = urlparse(trace.meta.request.url)
        qs = parse_qs(parsed.query)
        for key, values in qs.items():
            params[key].extend(values)
    return dict(params)


def _detect_base_url(traces: list[Trace]) -> str:
    """Detect the most common base URL from traces."""
    url_counts: dict[str, int] = defaultdict(int)
    for trace in traces:
        parsed = urlparse(trace.meta.request.url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        url_counts[base] += 1
    if url_counts:
        return max(url_counts, key=url_counts.get)
    return ""


def _detect_auth(traces: list[Trace]) -> AuthInfo:
    """Detect authentication patterns from traces."""
    auth_type = ""
    token_header = None
    token_prefix = None

    for trace in traces:
        auth_value = _get_header(trace.meta.request.headers, "authorization")
        if auth_value:
            token_header = "Authorization"
            if auth_value.startswith("Bearer "):
                auth_type = "bearer_token"
                token_prefix = "Bearer"
            elif auth_value.startswith("Basic "):
                auth_type = "basic"
                token_prefix = "Basic"
            else:
                auth_type = "custom"
            break

    # Look for cookie-based auth
    if not auth_type:
        for trace in traces:
            cookie = _get_header(trace.meta.request.headers, "cookie")
            if cookie and any(
                name in cookie.lower()
                for name in ["session", "token", "auth", "jwt"]
            ):
                auth_type = "cookie"
                break

    return AuthInfo(
        type=auth_type,
        token_header=token_header,
        token_prefix=token_prefix,
    )


def _build_ws_specs(ws_connections: list[WsConnection]) -> WebSocketProtocol:
    """Build WebSocket protocol specs."""
    specs: list[WsConnectionSpec] = []
    for ws_conn in ws_connections:
        proto = detect_ws_protocol(ws_conn)

        messages: list[WsMessageSpec] = []
        for msg in ws_conn.messages:
            payload_example = None
            payload_schema = None
            if msg.payload:
                try:
                    data = json.loads(msg.payload)
                    payload_example = data
                    if isinstance(data, dict):
                        payload_schema = _infer_json_schema([data])
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

            messages.append(
                WsMessageSpec(
                    direction=msg.meta.direction,
                    label=f"{msg.meta.direction}_{msg.meta.id}",
                    payload_schema=payload_schema,
                    example_payload=payload_example,
                )
            )

        specs.append(
            WsConnectionSpec(
                id=ws_conn.meta.id,
                url=ws_conn.meta.url,
                subprotocol=proto if proto != "unknown" else None,
                messages=messages,
            )
        )

    return WebSocketProtocol(connections=specs)


def _get_header(headers: list, name: str) -> str | None:
    """Get a header value by name (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.name.lower() == name_lower:
            return h.value
    return None
