"""Build an enriched API spec from a capture bundle using LLM-first analysis.

Pipeline:
1. Extract (method, url) pairs from traces
2. LLM groups URLs into endpoint patterns
3. For each group: mechanical extraction (query params, response codes, schemas)
   + LLM enrichment (business purpose, user story)
4. LLM auth analysis
5. LLM business context
6. Assemble spec
7. Mechanical validation
8. LLM correction if needed (one iteration)
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from cli.analyze.correlator import Correlation, correlate
from cli.analyze.llm import (
    EndpointGroup,
    analyze_auth,
    analyze_business_context,
    analyze_endpoint_detail,
    analyze_endpoints,
    correct_spec,
    detect_api_base_url,
)
from cli.analyze.protocol import detect_ws_protocol
from cli.analyze.validator import validate_spec
from cli.capture.models import CaptureBundle, Context, Trace, WsConnection
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


async def build_spec(
    bundle: CaptureBundle,
    client,
    model: str,
    source_filename: str = "",
    on_progress=None,
    enable_debug: bool = False,
) -> ApiSpec:
    """Build an enriched API spec from a capture bundle (LLM-first pipeline).

    Args:
        bundle: The loaded capture bundle.
        client: An Anthropic async client.
        model: The model to use for LLM calls.
        source_filename: The filename of the capture bundle.
        on_progress: Optional callback(message: str) for progress updates.
    """

    def progress(msg: str):
        if on_progress:
            on_progress(msg)

    # Create debug directory for this run
    debug_dir = None
    if enable_debug:
        run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        debug_dir = Path("debug") / run_ts
        debug_dir.mkdir(parents=True, exist_ok=True)
        progress(f"Debug logs → {debug_dir}")

    all_traces = list(bundle.traces)
    correlations = correlate(bundle)

    # Step 1: Extract (method, url) pairs
    url_method_pairs = [
        (t.meta.request.method.upper(), t.meta.request.url) for t in all_traces
    ]

    # Step 1b: LLM detects the business API base URL
    progress("Detecting API base URL (LLM)...")
    base_url = await detect_api_base_url(client, model, url_method_pairs, debug_dir=debug_dir)
    progress(f"  API base URL: {base_url}")

    # Step 1c: Filter traces to those matching the base URL
    total_before = len(all_traces)
    all_traces = [t for t in all_traces if t.meta.request.url.startswith(base_url)]
    progress(f"  Kept {len(all_traces)}/{total_before} traces under {base_url}")

    # Recalculate url_method_pairs from filtered traces
    url_method_pairs = [
        (t.meta.request.method.upper(), t.meta.request.url) for t in all_traces
    ]

    # Step 2: LLM groups URLs into endpoint patterns
    progress("Grouping URLs into endpoints (LLM)...")
    endpoint_groups = await analyze_endpoints(client, model, url_method_pairs, debug_dir=debug_dir)

    # Step 3: For each group, do mechanical extraction + LLM enrichment
    if debug_dir is not None and len(endpoint_groups) > 10:
        progress(f"Debug mode: limiting LLM enrichment to 10/{len(endpoint_groups)} endpoints")
        endpoint_groups = endpoint_groups[:10]
    progress(f"Enriching {len(endpoint_groups)} endpoints...")
    trace_map = {t.meta.id: t for t in all_traces}
    endpoints: list[EndpointSpec] = []
    app_name = (
        bundle.manifest.app.name + " API" if bundle.manifest.app.name else "Discovered API"
    )

    for i, group in enumerate(endpoint_groups, 1):
        progress(f"  [{i}/{len(endpoint_groups)}] {group.method} {group.pattern}")
        # Find traces that belong to this group
        group_traces = _find_traces_for_group(group, all_traces)

        # Mechanical extraction
        endpoint = _build_endpoint_mechanical(
            group.method, group.pattern, group_traces, correlations
        )

        # Prepare summary for LLM
        summary = _prepare_endpoint_summary(
            endpoint, group_traces, correlations, app_name, base_url
        )

        # LLM enrichment
        try:
            enrichment = await analyze_endpoint_detail(client, model, summary, debug_dir=debug_dir)
            _apply_enrichment(endpoint, enrichment)
        except Exception:
            pass  # LLM enrichment is best-effort

        endpoints.append(endpoint)

    # Step 4: Auth analysis
    progress("Analyzing authentication (LLM)...")
    auth_summary = _prepare_auth_summary(all_traces)
    try:
        auth = await analyze_auth(client, model, auth_summary, debug_dir=debug_dir)
    except Exception:
        auth = _detect_auth_mechanical(all_traces)

    # Step 5: Business context
    progress("Analyzing business context (LLM)...")
    ep_summaries = [
        f"- {ep.method} {ep.path}: {ep.business_purpose or '(unknown)'}"
        for ep in endpoints
    ]
    try:
        business_context, glossary = await analyze_business_context(
            client, model, ep_summaries, app_name, base_url, debug_dir=debug_dir,
        )
    except Exception:
        business_context = BusinessContext(
            domain="",
            description=f"API discovered from {bundle.manifest.app.base_url}",
        )
        glossary = {}

    # Step 5.5: WebSocket specs
    ws_specs = _build_ws_specs(bundle.ws_connections)

    # Step 6: Assemble spec
    spec = ApiSpec(
        name=app_name,
        discovery_date=datetime.now(timezone.utc).isoformat(),
        source_captures=[source_filename] if source_filename else [],
        business_context=business_context,
        auth=auth,
        protocols=Protocols(
            rest=RestProtocol(base_url=base_url, endpoints=endpoints),
            websocket=ws_specs,
        ),
        business_glossary=glossary,
    )

    # Step 7: Validate
    progress("Validating spec against traces...")
    errors = validate_spec(spec, all_traces)

    # Step 8: Correct if needed (one iteration)
    if errors:
        progress(f"Found {len(errors)} validation errors, requesting LLM correction...")
        try:
            spec_dict = json.loads(spec.model_dump_json(by_alias=True))
            error_dicts = [e.to_dict() for e in errors]
            corrected_dict = await correct_spec(client, model, spec_dict, error_dicts, debug_dir=debug_dir)
            spec = ApiSpec.model_validate(corrected_dict)

            # Re-validate (informational only, no second correction)
            errors2 = validate_spec(spec, all_traces)
            if errors2:
                progress(f"  {len(errors2)} errors remain after correction")
            else:
                progress("  All errors resolved")
        except Exception:
            progress("  Correction failed, keeping original spec")

    return spec


def _find_traces_for_group(group: EndpointGroup, traces: list[Trace]) -> list[Trace]:
    """Find traces whose URLs are listed in the endpoint group."""
    url_set = set(group.urls)
    matched = [
        t for t in traces
        if t.meta.request.url in url_set
        and t.meta.request.method.upper() == group.method
    ]

    # Also try pattern matching to catch traces the LLM didn't list
    pattern_re = _pattern_to_regex(group.pattern)
    for t in traces:
        if t not in matched:
            parsed = urlparse(t.meta.request.url)
            if (
                t.meta.request.method.upper() == group.method
                and pattern_re.match(parsed.path)
            ):
                matched.append(t)

    return matched


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert /api/users/{user_id} to a regex pattern."""
    parts = re.split(r"\{[^}]+\}", pattern)
    placeholders = re.findall(r"\{[^}]+\}", pattern)
    regex = ""
    for i, part in enumerate(parts):
        regex += re.escape(part)
        if i < len(placeholders):
            regex += r"[^/]+"
    return re.compile(f"^{regex}$")


def _build_endpoint_mechanical(
    method: str,
    path_pattern: str,
    traces: list[Trace],
    correlations: list[Correlation],
) -> EndpointSpec:
    """Build an endpoint spec from grouped traces (mechanical only)."""
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
                break

    request_spec = _build_request_spec(traces, path_pattern)
    response_specs = _build_response_specs(traces)

    requires_auth = any(
        _get_header(t.meta.request.headers, "authorization") is not None
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
        requires_auth=requires_auth,
        observed_count=len(traces),
        source_trace_refs=[t.meta.id for t in traces],
    )


def _prepare_endpoint_summary(
    endpoint: EndpointSpec,
    traces: list[Trace],
    correlations: list[Correlation],
    app_name: str,
    base_url: str,
) -> dict:
    """Prepare a summary dict for the LLM enrichment call."""
    sample_requests = []
    sample_responses = []

    for t in traces[:3]:  # Limit to 3 samples
        req = {"method": t.meta.request.method, "url": t.meta.request.url}
        if t.request_body:
            try:
                req["body"] = json.loads(t.request_body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                req["body_size"] = len(t.request_body)
        sample_requests.append(req)

        resp = {"status": t.meta.response.status}
        if t.response_body:
            try:
                body = json.loads(t.response_body)
                # Truncate large bodies
                resp["body"] = _truncate_json(body, max_keys=10)
            except (json.JSONDecodeError, UnicodeDecodeError):
                resp["body_size"] = len(t.response_body)
        sample_responses.append(resp)

    triggers = []
    for trig in endpoint.ui_triggers:
        triggers.append({
            "action": trig.action,
            "element_text": trig.element_text,
            "element_selector": trig.element_selector,
            "page_url": trig.page_url,
        })

    return {
        "method": endpoint.method,
        "pattern": endpoint.path,
        "observed_count": endpoint.observed_count,
        "app_name": app_name,
        "base_url": base_url,
        "ui_triggers": triggers,
        "sample_requests": sample_requests,
        "sample_responses": sample_responses,
    }


def _truncate_json(obj, max_keys: int = 10):
    """Truncate a JSON-like object for LLM consumption."""
    if isinstance(obj, dict):
        items = list(obj.items())[:max_keys]
        return {k: _truncate_json(v, max_keys) for k, v in items}
    if isinstance(obj, list):
        return [_truncate_json(item, max_keys) for item in obj[:3]]
    if isinstance(obj, str) and len(obj) > 200:
        return obj[:200] + "..."
    return obj


def _apply_enrichment(endpoint: EndpointSpec, enrichment) -> None:
    """Apply LLM enrichment to an endpoint spec."""
    if enrichment.business_purpose:
        endpoint.business_purpose = enrichment.business_purpose
    if enrichment.user_story:
        endpoint.user_story = enrichment.user_story
    if enrichment.correlation_confidence is not None:
        try:
            endpoint.correlation_confidence = float(enrichment.correlation_confidence)
        except (ValueError, TypeError):
            pass

    # Apply parameter meanings
    for param in endpoint.request.parameters:
        if param.name in enrichment.parameter_meanings:
            param.business_meaning = enrichment.parameter_meanings[param.name]

    # Apply response meanings
    for resp in endpoint.responses:
        if resp.status in enrichment.response_meanings:
            resp.business_meaning = enrichment.response_meanings[resp.status]

    # Apply trigger explanations
    for i, trigger in enumerate(endpoint.ui_triggers):
        if i < len(enrichment.trigger_explanations):
            trigger.user_explanation = enrichment.trigger_explanations[i]


def _prepare_auth_summary(traces: list[Trace]) -> list[dict]:
    """Prepare trace summaries relevant to authentication."""
    summaries = []
    for t in traces:
        headers_dict = {h.name: h.value for h in t.meta.request.headers}
        resp_headers_dict = {h.name: h.value for h in t.meta.response.headers}

        # Include traces with auth-like characteristics
        is_auth_related = (
            "authorization" in {h.name.lower() for h in t.meta.request.headers}
            or "set-cookie" in {h.name.lower() for h in t.meta.response.headers}
            or any(kw in t.meta.request.url.lower() for kw in [
                "auth", "login", "token", "oauth", "callback", "session", "signin"
            ])
            or t.meta.response.status in (401, 403)
        )

        if not is_auth_related:
            continue

        summary: dict = {
            "method": t.meta.request.method,
            "url": t.meta.request.url,
            "response_status": t.meta.response.status,
            "request_headers": _sanitize_headers(headers_dict),
            "response_headers": _sanitize_headers(resp_headers_dict),
        }

        if t.request_body:
            try:
                body = json.loads(t.request_body)
                summary["request_body_snippet"] = _truncate_json(body, max_keys=5)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        if t.response_body:
            try:
                body = json.loads(t.response_body)
                summary["response_body_snippet"] = _truncate_json(body, max_keys=5)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        summaries.append(summary)

    # If no auth-specific traces found, include a sample of headers from all traces
    if not summaries and traces:
        for t in traces[:5]:
            headers_dict = {h.name: h.value for h in t.meta.request.headers}
            summaries.append({
                "method": t.meta.request.method,
                "url": t.meta.request.url,
                "response_status": t.meta.response.status,
                "request_headers": _sanitize_headers(headers_dict),
            })

    return summaries


def _sanitize_headers(headers: dict) -> dict:
    """Redact long token values but keep header structure visible."""
    sanitized = {}
    for k, v in headers.items():
        if k.lower() in ("authorization", "cookie", "set-cookie") and len(v) > 30:
            sanitized[k] = v[:30] + "...[redacted]"
        else:
            sanitized[k] = v
    return sanitized


def _has_auth_cookie(trace: Trace) -> bool:
    """Check if a trace has auth-related cookies."""
    cookie = _get_header(trace.meta.request.headers, "cookie")
    if cookie and any(
        name in cookie.lower() for name in ["session", "token", "auth", "jwt"]
    ):
        return True
    return False


def _detect_auth_mechanical(traces: list[Trace]) -> AuthInfo:
    """Fallback mechanical auth detection."""
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

    if not auth_type:
        for trace in traces:
            if _has_auth_cookie(trace):
                auth_type = "cookie"
                break

    return AuthInfo(type=auth_type, token_header=token_header, token_prefix=token_prefix)


# ============================================================================
# Mechanical extraction utilities (shared with validator)
# ============================================================================


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
