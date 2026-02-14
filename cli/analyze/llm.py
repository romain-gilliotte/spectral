"""LLM client for semantic inference using the Anthropic API.

This module provides specialized LLM calls for the LLM-first analysis pipeline:
- analyze_endpoints: group URLs into endpoint patterns
- analyze_auth: detect authentication mechanisms
- analyze_endpoint_detail: enrich a single endpoint with business meaning
- analyze_business_context: infer overall business context and glossary
- correct_spec: fix validation errors found by the mechanical validator
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

def _save_debug(debug_dir: Path | None, call_name: str, prompt: str, response_text: str) -> None:
    """Save an LLM call's prompt and response to the debug directory."""
    if debug_dir is None:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    path = debug_dir / f"{ts}_{call_name}"
    path.write_text(f"=== PROMPT ===\n{prompt}\n\n=== RESPONSE ===\n{response_text}\n")


from cli.formats.api_spec import (
    ApiSpec,
    AuthInfo,
    BusinessContext,
    EndpointSpec,
    ParameterSpec,
    RequestSpec,
    ResponseSpec,
    UiTrigger,
    WorkflowStep,
)


@dataclass
class EndpointGroup:
    """An LLM-identified endpoint group."""

    method: str
    pattern: str
    urls: list[str] = field(default_factory=list)


@dataclass
class EndpointEnrichment:
    """LLM-inferred semantic information for an endpoint."""

    business_purpose: str | None = None
    user_story: str | None = None
    correlation_confidence: float | None = None
    parameter_meanings: dict[str, str] = field(default_factory=dict)
    response_meanings: dict[int, str] = field(default_factory=dict)
    trigger_explanations: list[str] = field(default_factory=list)


def _extract_json(text: str) -> dict | list:
    """Extract JSON from LLM response text, handling markdown code blocks."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } or [ ... ] block
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        if start == -1:
            continue
        # Find matching end
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}")


# --- Investigation tools for LLM tool_use ---

INVESTIGATION_TOOLS = [
    {
        "name": "decode_base64",
        "description": "Decode a base64-encoded string (standard or URL-safe, auto-padding). Returns the decoded text (UTF-8) or a hex dump if the content is binary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "description": "The base64-encoded string to decode.",
                }
            },
            "required": ["value"],
        },
    },
    {
        "name": "decode_url",
        "description": "URL-decode a percent-encoded string (e.g. %20 → space, %2F → /).",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "description": "The percent-encoded string to decode.",
                }
            },
            "required": ["value"],
        },
    },
    {
        "name": "decode_jwt",
        "description": "Decode a JWT token (without signature verification). Returns the decoded header and payload as JSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": "The JWT token string (header.payload.signature).",
                }
            },
            "required": ["token"],
        },
    },
]


def _execute_decode_base64(value: str) -> str:
    """Decode a base64 string (standard or URL-safe, with auto-padding)."""
    # Add missing padding
    padded = value + "=" * (-len(value) % 4)
    raw = None
    # Try URL-safe first (most common in URLs), then standard.
    # urlsafe_b64decode doesn't accept validate=, so we validate manually.
    if re.fullmatch(r"[A-Za-z0-9\-_=]+", padded):
        try:
            raw = base64.urlsafe_b64decode(padded)
        except Exception:
            pass
    if raw is None and re.fullmatch(r"[A-Za-z0-9+/=]+", padded):
        try:
            raw = base64.b64decode(padded, validate=True)
        except Exception:
            pass
    if raw is None:
        raise ValueError(f"Cannot base64-decode: {value[:80]}")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"<binary: {raw.hex()}>"


def _execute_decode_url(value: str) -> str:
    """URL-decode a percent-encoded string."""
    return unquote(value)


def _execute_decode_jwt(token: str) -> str:
    """Decode a JWT header + payload (no signature verification)."""
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("Invalid JWT: expected at least 2 dot-separated parts")
    decoded = {}
    for label, part in zip(("header", "payload"), parts[:2]):
        padded = part + "=" * (-len(part) % 4)
        raw = base64.urlsafe_b64decode(padded)
        decoded[label] = json.loads(raw)
    return json.dumps(decoded, indent=2)


_TOOL_EXECUTORS: dict[str, callable] = {
    "decode_base64": lambda inp: _execute_decode_base64(inp["value"]),
    "decode_url": lambda inp: _execute_decode_url(inp["value"]),
    "decode_jwt": lambda inp: _execute_decode_jwt(inp["token"]),
}


async def _call_with_tools(
    client,
    model: str,
    messages: list[dict],
    tools: list[dict],
    executors: dict[str, callable],
    max_tokens: int = 4096,
    max_iterations: int = 10,
    debug_dir: Path | None = None,
    call_name: str = "call",
) -> str:
    """Call the LLM with tool_use support, looping until a text response is produced."""
    for _ in range(max_iterations):
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            # Extract text from content blocks
            parts = []
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    parts.append(block.text)
            text = "\n".join(parts)
            _save_debug(debug_dir, call_name, messages[0]["content"], text)
            return text

        # Process tool calls
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            executor = executors.get(block.name)
            if executor is None:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Unknown tool: {block.name}",
                    "is_error": True,
                })
                continue
            try:
                result = executor(block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            except Exception as exc:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {exc}",
                    "is_error": True,
                })
        messages.append({"role": "user", "content": tool_results})

    raise ValueError(f"_call_with_tools exceeded {max_iterations} iterations")


def _compact_url(url: str) -> str:
    """Strip query string and replace long base64-encoded path segments with a placeholder.

    Only compacts segments that are >60 chars AND decode to valid UTF-8 text via base64.
    This avoids false positives on hex IDs, normal words, etc.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    segments = parsed.path.split("/")
    compacted = []
    for seg in segments:
        if len(seg) > 60:
            try:
                text = _execute_decode_base64(seg)
                if not text.startswith("<binary:"):
                    compacted.append(f"<base64:{len(seg)}chars>")
                    continue
            except ValueError:
                pass
        compacted.append(seg)
    return f"{parsed.scheme}://{parsed.netloc}{'/'.join(compacted)}"


async def detect_api_base_url(
    client, model: str, url_method_pairs: list[tuple[str, str]],
    debug_dir: Path | None = None,
) -> str:
    """Ask the LLM to identify the business API base URL from captured traffic.

    Input: list of (method, url) pairs (deduplicated).
    Output: a base URL string like "https://www.example.com/api" or "https://api.example.com".
    """
    unique_pairs = sorted(set(url_method_pairs))
    compacted_pairs = sorted(set(
        (method, _compact_url(url)) for method, url in unique_pairs
    ))
    lines = [f"  {method} {url}" for method, url in compacted_pairs]

    prompt = f"""You are analyzing HTTP traffic captured from a web application.
Identify the base URL of the **business API** (the main application API, not CDN, analytics, tracking, fonts, or third-party services).

The base URL can be:
- Just the origin: https://api.example.com
- Origin + path prefix: https://www.example.com/api

Rules:
- Pick the single most important API base URL — the one serving the app's core business endpoints.
- Ignore CDN domains, analytics (google-analytics, hotjar, segment, etc.), ad trackers, font services, static asset hosts.
- If the API endpoints share a common path prefix (e.g. /api/v1), include it.
- Return ONLY the base URL string, no trailing slash.

Observed requests:
{chr(10).join(lines)}

Respond with a JSON object:
{{"base_url": "https://..."}}"""

    text = await _call_with_tools(
        client,
        model,
        [{"role": "user", "content": prompt}],
        INVESTIGATION_TOOLS,
        _TOOL_EXECUTORS,
        debug_dir=debug_dir,
        call_name="detect_api_base_url",
    )

    result = _extract_json(text)
    if isinstance(result, dict) and "base_url" in result:
        return result["base_url"].rstrip("/")
    raise ValueError(f"Expected {{\"base_url\": \"...\"}} from detect_api_base_url, got: {text[:200]}")


async def analyze_endpoints(
    client, model: str, url_method_pairs: list[tuple[str, str]],
    debug_dir: Path | None = None,
) -> list[EndpointGroup]:
    """Ask the LLM to group URLs into endpoint patterns.

    Input: list of (method, url) pairs (deduplicated).
    Output: list of EndpointGroup with path patterns and assigned URLs.
    """
    # Deduplicate, compact URLs (strip query strings, truncate base64 blobs)
    unique_pairs = sorted(set(url_method_pairs))
    compacted_pairs = sorted(set(
        (method, _compact_url(url)) for method, url in unique_pairs
    ))
    lines = [f"  {method} {url}" for method, url in compacted_pairs]

    # Build mapping from compacted URL back to original URLs
    compact_to_originals: dict[tuple[str, str], list[str]] = {}
    for method, url in unique_pairs:
        key = (method, _compact_url(url))
        compact_to_originals.setdefault(key, []).append(url)

    prompt = f"""You are analyzing HTTP traffic captured from a web application.
Group these observed URLs into API endpoints. For each group, identify the path pattern
with parameters (use {{param_name}} syntax for variable segments).

Rules:
- Variable path segments (IDs, hashes, encoded values) become parameters like {{id}}, {{project_id}}, etc.
- Even if you only see ONE value for a segment, if it looks like an ID (numeric, UUID, hash, base64-like), parameterize it.
- Segments marked <base64:Nchars> are base64-encoded parameters — treat them as variable segments.
- Group URLs that represent the same logical endpoint together.
- Use the resource name before an ID to name the parameter (e.g., /projects/123 → /projects/{{project_id}}).
- Only include the path (no scheme, host, or query string) in the pattern.

You have investigation tools: decode_base64, decode_url, decode_jwt.
Use them when URL segments look opaque (base64-encoded, percent-encoded, or JWT tokens).
Decoding opaque segments will help you understand what they represent and group URLs correctly.

Observed requests:
{chr(10).join(lines)}

Respond with a JSON array:
[
  {{"method": "GET", "pattern": "/api/users/{{user_id}}/orders", "urls": ["https://example.com/api/users/123/orders", "https://example.com/api/users/456/orders"]}}
]"""

    text = await _call_with_tools(
        client,
        model,
        [{"role": "user", "content": prompt}],
        INVESTIGATION_TOOLS,
        _TOOL_EXECUTORS,
        debug_dir=debug_dir,
        call_name="analyze_endpoints",
    )

    result = _extract_json(text)
    if not isinstance(result, list):
        raise ValueError("Expected a JSON array from analyze_endpoints")

    # Expand compacted URLs back to originals so the rest of the pipeline
    # can match them against actual traces.
    groups = []
    for item in result:
        compacted_urls = item.get("urls", [])
        original_urls = []
        for curl in compacted_urls:
            key = (item["method"], curl)
            if key in compact_to_originals:
                original_urls.extend(compact_to_originals[key])
            else:
                original_urls.append(curl)
        groups.append(
            EndpointGroup(
                method=item["method"],
                pattern=item["pattern"],
                urls=original_urls,
            )
        )
    return groups


async def analyze_auth(
    client, model: str, auth_traces_summary: list[dict],
    debug_dir: Path | None = None,
) -> AuthInfo:
    """Ask the LLM to analyze authentication from trace summaries.

    Input: list of dicts with keys: url, method, request_headers, response_status,
           request_body_snippet, response_body_snippet.
    Output: AuthInfo filled with detected auth info.
    """
    prompt = f"""Analyze the authentication mechanism used by this web application.

Here are relevant traces (login flows, token exchanges, authenticated requests):

{json.dumps(auth_traces_summary)[:6000]}

Identify:
1. "type": The auth type (e.g., "bearer_token", "oauth2", "cookie", "basic", "api_key", "none")
2. "obtain_flow": How the token is obtained (e.g., "oauth2_authorization_code", "login_form", "api_key")
3. "token_header": The header carrying the auth token (e.g., "Authorization", "Cookie")
4. "token_prefix": The prefix before the token value (e.g., "Bearer", "Basic", null)
5. "business_process": Human description of how auth works
6. "user_journey": Array of steps describing the login process
7. "discovery_notes": Any additional observations

If you see OAuth2 flows (auth0, okta, etc.), detect them even if the Authorization header is not used directly.
Look for cookies, URL tokens, and cross-origin auth redirects.

Respond in JSON."""

    response = await client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    _save_debug(debug_dir, "analyze_auth", prompt, response.content[0].text)
    data = _extract_json(response.content[0].text)
    if not isinstance(data, dict):
        return AuthInfo()

    return AuthInfo(
        type=data.get("type", ""),
        obtain_flow=data.get("obtain_flow", ""),
        business_process=data.get("business_process"),
        user_journey=data.get("user_journey", []),
        token_header=data.get("token_header"),
        token_prefix=data.get("token_prefix"),
        refresh_endpoint=data.get("refresh_endpoint"),
        discovery_notes=data.get("discovery_notes"),
    )


async def analyze_endpoint_detail(
    client,
    model: str,
    endpoint_summary: dict,
    debug_dir: Path | None = None,
) -> EndpointEnrichment:
    """Ask the LLM to enrich a single endpoint with business meaning.

    Input: dict with keys: method, pattern, sample_requests, sample_responses,
           ui_triggers, app_name, base_url.
    Output: EndpointEnrichment with business semantics.
    """
    prompt = f"""Analyze this API endpoint discovered from a web application:

Endpoint: {endpoint_summary['method']} {endpoint_summary['pattern']}
Application: {endpoint_summary.get('app_name', 'Unknown')}
Base URL: {endpoint_summary.get('base_url', '')}
Observed {endpoint_summary.get('observed_count', 0)} times.

UI triggers (what the user did to cause this API call):
{chr(10).join(json.dumps(t) for t in endpoint_summary.get('ui_triggers', []))[:1000]}

Sample requests:
{chr(10).join(json.dumps(r) for r in endpoint_summary.get('sample_requests', []))[:2000]}

Sample responses:
{chr(10).join(json.dumps(r) for r in endpoint_summary.get('sample_responses', []))[:2000]}

Provide:
1. "business_purpose": Concise description of what this endpoint does in business terms
2. "user_story": "As a [persona], I want to [action] so that [goal]"
3. "correlation_confidence": 0.0-1.0 confidence in the UI↔API correlation
4. "parameter_meanings": {{param_name: "business meaning"}} for each parameter
5. "response_meanings": {{status_code: "business meaning"}} for each observed status
6. "trigger_explanations": Array of natural language descriptions for each UI trigger

Respond in JSON."""

    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    endpoint_label = f"{endpoint_summary['method']}_{endpoint_summary['pattern']}"
    endpoint_label = re.sub(r"[^a-zA-Z0-9_-]", "_", endpoint_label)
    _save_debug(debug_dir, f"analyze_endpoint_detail_{endpoint_label}", prompt, response.content[0].text)
    data = _extract_json(response.content[0].text)
    if not isinstance(data, dict):
        return EndpointEnrichment()

    # Parse response_meanings keys to int
    response_meanings = {}
    for k, v in data.get("response_meanings", {}).items():
        try:
            response_meanings[int(k)] = v
        except (ValueError, TypeError):
            pass

    return EndpointEnrichment(
        business_purpose=data.get("business_purpose"),
        user_story=data.get("user_story"),
        correlation_confidence=data.get("correlation_confidence"),
        parameter_meanings=data.get("parameter_meanings", {}),
        response_meanings=response_meanings,
        trigger_explanations=data.get("trigger_explanations", []),
    )


async def analyze_business_context(
    client, model: str, endpoint_summaries: list[str], app_name: str, base_url: str,
    debug_dir: Path | None = None,
) -> tuple[BusinessContext, dict[str, str]]:
    """Ask the LLM to infer overall business context and glossary.

    Returns (BusinessContext, business_glossary).
    """
    prompt = f"""Based on these API endpoints discovered from "{app_name}" ({base_url}):

{chr(10).join(endpoint_summaries)}

Provide:
1. "domain": The business domain (e.g., "E-commerce", "Project Management", "Energy Management")
2. "description": A one-line description of this API
3. "user_personas": Array of user types who would use this
4. "key_workflows": Array of {{"name": "...", "description": "...", "steps": [...]}}
5. "business_glossary": {{term: "definition"}} for domain-specific terms found in the API

Respond in JSON."""

    response = await client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    _save_debug(debug_dir, "analyze_business_context", prompt, response.content[0].text)
    data = _extract_json(response.content[0].text)
    if not isinstance(data, dict):
        return BusinessContext(), {}

    workflows = []
    for wf in data.get("key_workflows", []):
        if isinstance(wf, dict):
            workflows.append(
                WorkflowStep(
                    name=wf.get("name", ""),
                    description=wf.get("description", ""),
                    steps=wf.get("steps", []),
                )
            )

    context = BusinessContext(
        domain=data.get("domain", ""),
        description=data.get("description", ""),
        user_personas=data.get("user_personas", []),
        key_workflows=workflows,
    )
    glossary = data.get("business_glossary", {})
    if not isinstance(glossary, dict):
        glossary = {}

    return context, glossary


async def correct_spec(
    client, model: str, spec_json: dict, errors: list[dict],
    debug_dir: Path | None = None,
) -> dict:
    """Ask the LLM to correct a spec based on validation errors.

    Input: the spec as a dict + list of structured validation errors.
    Output: corrected spec as a dict.
    """
    # Only send endpoint-relevant parts to keep tokens low
    endpoints_json = json.dumps(spec_json.get("protocols", {}).get("rest", {}).get("endpoints", []))

    prompt = f"""The following API spec has validation errors when checked against the actual captured traffic.

Endpoints:
{endpoints_json[:8000]}

Validation errors:
{json.dumps(errors)[:4000]}

Fix the spec to resolve these errors. Common fixes:
- If a trace URL doesn't match any endpoint pattern, adjust the pattern or create a new endpoint
- If a URL doesn't match its assigned endpoint pattern, fix the pattern
- Merge endpoints that are actually the same (different patterns matching same logical endpoint)

Return the corrected endpoints as a JSON array with the same structure."""

    response = await client.messages.create(
        model=model,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    _save_debug(debug_dir, "correct_spec", prompt, response.content[0].text)
    corrected = _extract_json(response.content[0].text)
    if isinstance(corrected, list):
        spec_json = dict(spec_json)  # shallow copy
        protocols = dict(spec_json.get("protocols", {}))
        rest = dict(protocols.get("rest", {}))
        rest["endpoints"] = corrected
        protocols["rest"] = rest
        spec_json["protocols"] = protocols
    return spec_json
