"""LLM client for semantic inference using the Anthropic API.

This module provides specialized LLM calls for the LLM-first analysis pipeline:
- analyze_endpoints: group URLs into endpoint patterns
- analyze_auth: detect authentication mechanisms
- analyze_endpoint_detail: enrich a single endpoint with business meaning
- analyze_business_context: infer overall business context and glossary
- correct_spec: fix validation errors found by the mechanical validator
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

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


async def analyze_endpoints(
    client, model: str, url_method_pairs: list[tuple[str, str]]
) -> list[EndpointGroup]:
    """Ask the LLM to group URLs into endpoint patterns.

    Input: list of (method, url) pairs (deduplicated).
    Output: list of EndpointGroup with path patterns and assigned URLs.
    """
    # Deduplicate and format
    unique_pairs = sorted(set(url_method_pairs))
    lines = [f"  {method} {url}" for method, url in unique_pairs]

    prompt = f"""You are analyzing HTTP traffic captured from a web application.
Group these observed URLs into API endpoints. For each group, identify the path pattern
with parameters (use {{param_name}} syntax for variable segments).

Rules:
- Variable path segments (IDs, hashes, encoded values) become parameters like {{id}}, {{project_id}}, etc.
- Even if you only see ONE value for a segment, if it looks like an ID (numeric, UUID, hash, base64-like), parameterize it.
- Group URLs that represent the same logical endpoint together.
- Use the resource name before an ID to name the parameter (e.g., /projects/123 → /projects/{{project_id}}).
- Ignore query parameters for grouping — they're handled separately.
- Only include the path (no scheme, host, or query string) in the pattern.

Observed requests:
{chr(10).join(lines)}

Respond with a JSON array:
[
  {{"method": "GET", "pattern": "/api/users/{{user_id}}/orders", "urls": ["https://example.com/api/users/123/orders", "https://example.com/api/users/456/orders"]}}
]"""

    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    result = _extract_json(response.content[0].text)
    if not isinstance(result, list):
        raise ValueError("Expected a JSON array from analyze_endpoints")

    groups = []
    for item in result:
        groups.append(
            EndpointGroup(
                method=item["method"],
                pattern=item["pattern"],
                urls=item.get("urls", []),
            )
        )
    return groups


async def analyze_auth(
    client, model: str, auth_traces_summary: list[dict]
) -> AuthInfo:
    """Ask the LLM to analyze authentication from trace summaries.

    Input: list of dicts with keys: url, method, request_headers, response_status,
           request_body_snippet, response_body_snippet.
    Output: AuthInfo filled with detected auth info.
    """
    prompt = f"""Analyze the authentication mechanism used by this web application.

Here are relevant traces (login flows, token exchanges, authenticated requests):

{json.dumps(auth_traces_summary, indent=2)[:6000]}

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
{json.dumps(endpoint_summary.get('ui_triggers', []), indent=2)[:1000]}

Sample requests:
{json.dumps(endpoint_summary.get('sample_requests', []), indent=2)[:2000]}

Sample responses:
{json.dumps(endpoint_summary.get('sample_responses', []), indent=2)[:2000]}

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
    client, model: str, endpoint_summaries: list[str], app_name: str, base_url: str
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
    client, model: str, spec_json: dict, errors: list[dict]
) -> dict:
    """Ask the LLM to correct a spec based on validation errors.

    Input: the spec as a dict + list of structured validation errors.
    Output: corrected spec as a dict.
    """
    # Only send endpoint-relevant parts to keep tokens low
    endpoints_json = json.dumps(spec_json.get("protocols", {}).get("rest", {}).get("endpoints", []), indent=2)

    prompt = f"""The following API spec has validation errors when checked against the actual captured traffic.

Endpoints:
{endpoints_json[:8000]}

Validation errors:
{json.dumps(errors, indent=2)[:4000]}

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

    corrected = _extract_json(response.content[0].text)
    if isinstance(corrected, list):
        spec_json = dict(spec_json)  # shallow copy
        protocols = dict(spec_json.get("protocols", {}))
        rest = dict(protocols.get("rest", {}))
        rest["endpoints"] = corrected
        protocols["rest"] = rest
        spec_json["protocols"] = protocols
    return spec_json
