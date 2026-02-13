"""LLM client for semantic inference using the Anthropic API.

This module enriches an API spec with business meaning, user stories,
and other semantic information that cannot be determined mechanically.
"""

from __future__ import annotations

import json
import os

from cli.formats.api_spec import ApiSpec, EndpointSpec


def is_llm_available() -> bool:
    """Check if the Anthropic API key is configured."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


async def enrich_spec(
    spec: ApiSpec, model: str = "claude-sonnet-4-5-20250929"
) -> ApiSpec:
    """Enrich an API spec with LLM-inferred fields.

    Requires ANTHROPIC_API_KEY environment variable to be set.
    """
    import anthropic

    client = anthropic.AsyncAnthropic()

    # Enrich each endpoint
    for endpoint in spec.protocols.rest.endpoints:
        await _enrich_endpoint(client, model, endpoint, spec)

    # Enrich business context and glossary
    await _enrich_business_context(client, model, spec)

    return spec


async def _enrich_endpoint(
    client, model: str, endpoint: EndpointSpec, spec: ApiSpec
) -> None:
    """Enrich a single endpoint with LLM-inferred fields."""
    # Build a focused prompt for this endpoint
    triggers_desc = ""
    for t in endpoint.ui_triggers:
        triggers_desc += (
            f"  - User action: {t.action} on '{t.element_text}' "
            f"(selector: {t.element_selector}) on page {t.page_url}\n"
        )

    request_desc = ""
    for p in endpoint.request.parameters:
        request_desc += f"  - {p.name} ({p.location}): type={p.type}"
        if p.observed_values:
            request_desc += f", examples: {p.observed_values[:3]}"
        request_desc += "\n"

    response_desc = ""
    for r in endpoint.responses:
        response_desc += f"  - Status {r.status}"
        if r.example_body:
            body_str = json.dumps(r.example_body, indent=2)[:500]
            response_desc += f": {body_str}"
        response_desc += "\n"

    prompt = f"""Analyze this API endpoint discovered from a web application:

Endpoint: {endpoint.method} {endpoint.path}
Observed {endpoint.observed_count} times.

UI triggers (what the user did to cause this API call):
{triggers_desc or "  (no UI context captured)"}

Request parameters:
{request_desc or "  (none)"}

Response examples:
{response_desc or "  (none)"}

Application: {spec.name}
Base URL: {spec.protocols.rest.base_url}

Please provide:
1. business_purpose: A concise description of what this endpoint does in business terms
2. user_story: "As a [persona], I want to [action] so that [goal]"
3. For each UI trigger, a user_explanation in natural language
4. For each parameter, a business_meaning
5. For each response status, a business_meaning
6. correlation_confidence: 0.0-1.0 how confident you are in the UI↔API correlation

Respond in JSON format with these exact keys."""

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        result = json.loads(response.content[0].text)
        _apply_endpoint_enrichment(endpoint, result)
    except Exception:
        # LLM enrichment is best-effort — don't fail the pipeline
        pass


async def _enrich_business_context(client, model: str, spec: ApiSpec) -> None:
    """Enrich overall business context and glossary."""
    endpoint_summaries = []
    for ep in spec.protocols.rest.endpoints:
        endpoint_summaries.append(f"- {ep.method} {ep.path}: {ep.business_purpose or '(unknown)'}")

    prompt = f"""Based on these API endpoints discovered from "{spec.name}" ({spec.protocols.rest.base_url}):

{chr(10).join(endpoint_summaries)}

Please provide:
1. domain: The business domain (e.g., "E-commerce", "Banking", "Energy Management")
2. description: A one-line description of this API
3. user_personas: List of user types who would use this
4. key_workflows: List of workflows (name + description + steps)
5. business_glossary: Dictionary of domain-specific terms found in the API

Respond in JSON format."""

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        result = json.loads(response.content[0].text)
        _apply_context_enrichment(spec, result)
    except Exception:
        pass


def _apply_endpoint_enrichment(endpoint: EndpointSpec, data: dict) -> None:
    """Apply LLM enrichment data to an endpoint."""
    if "business_purpose" in data:
        endpoint.business_purpose = data["business_purpose"]
    if "user_story" in data:
        endpoint.user_story = data["user_story"]
    if "correlation_confidence" in data:
        try:
            endpoint.correlation_confidence = float(data["correlation_confidence"])
        except (ValueError, TypeError):
            pass


def _apply_context_enrichment(spec: ApiSpec, data: dict) -> None:
    """Apply LLM enrichment data to spec-level fields."""
    if "domain" in data:
        spec.business_context.domain = data["domain"]
    if "description" in data:
        spec.business_context.description = data["description"]
    if "user_personas" in data and isinstance(data["user_personas"], list):
        spec.business_context.user_personas = data["user_personas"]
    if "business_glossary" in data and isinstance(data["business_glossary"], dict):
        spec.business_glossary = data["business_glossary"]
