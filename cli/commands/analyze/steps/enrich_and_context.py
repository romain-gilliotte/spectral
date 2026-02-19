"""Step: Enrich endpoints with business semantics via parallel per-endpoint LLM calls."""

from __future__ import annotations

import asyncio
import json
from typing import Any, TypeGuard
from urllib.parse import urlparse

from cli.commands.analyze.steps.base import LLMStep
from cli.commands.analyze.steps.types import (
    Correlation,
    EndpointSpec,
    EnrichmentContext,
)
from cli.commands.analyze.tools import extract_json, save_debug
from cli.commands.analyze.utils import pattern_to_regex
from cli.commands.capture.types import Trace


class EnrichEndpointsStep(LLMStep[EnrichmentContext, list[EndpointSpec]]):
    """Parallel per-endpoint LLM calls to enrich each endpoint with business
    semantics: description, field descriptions for all schemas, response
    details, and discovery notes.
    """

    name = "enrich_endpoints"

    async def _execute(self, input: EnrichmentContext) -> list[EndpointSpec]:
        async def _enrich_one(ep: EndpointSpec) -> None:
            summary = _build_endpoint_summary(ep, input.traces, input.correlations)
            prompt = f"""You are analyzing a single API endpoint discovered from "{input.app_name}" ({input.base_url}).

Below is the endpoint's mechanical data as JSON Schema. Nested properties carry an "observed" array with sample values seen in real traffic — use these to understand business meaning.

{json.dumps(summary, indent=1)}

Provide a JSON response with these keys:
- "description": concise description of what this endpoint does in business terms (this becomes the OpenAPI summary)
- "field_descriptions": an object mirroring the schema structure with business descriptions for each field. Sub-keys:
  - "path_parameters": {{param_name: "description", ...}} (omit if no path parameters)
  - "query_parameters": {{param_name: "description", ...}} (omit if no query parameters)
  - "request_body": object mirroring the request body schema structure (omit if no request body)
  - "responses": {{status_code_string: object mirroring the response schema structure}} (omit if no response schemas)
  Rules for field_descriptions structure:
  - Leaf values are always description strings.
  - Nested objects mirror the nesting: {{"address": {{"city": "...", "zip": "..."}}}}
  - For arrays of objects, use the array field name as key with a flat object describing the item properties: {{"items": {{"name": "...", "price": "..."}}}}
  - NEVER use dot-paths or bracket notation like "items[].name". Always use nested objects.
- "response_details": {{status_code_string: {{"business_meaning": "...", "example_scenario": "...", "user_impact": "..." or null, "resolution": "..." or null}}}} for each observed status. For error statuses (4xx/5xx), include user_impact and resolution.
- "discovery_notes": observations, edge cases, or dependencies worth noting about this endpoint (or null)

Respond in JSON."""

            try:
                response: Any = await self.client.messages.create(
                    model=self.model,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )

                save_debug(
                    self.debug_dir,
                    f"enrich_{ep.id}",
                    prompt,
                    response.content[0].text,
                )
                data = extract_json(response.content[0].text)

                if isinstance(data, dict):
                    _apply_enrichment(ep, data)
            except Exception:
                pass  # Leave endpoint un-enriched on failure

        await asyncio.gather(*[_enrich_one(ep) for ep in input.endpoints])

        return input.endpoints


def _strip_root_observed(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of *schema* with ``observed`` removed from root properties only.

    Nested leaves keep their ``observed`` arrays (useful LLM context).
    Root-level ones are redundant with the property name and type.
    """
    props = schema.get("properties")
    if not _is_json_dict(props):
        return schema
    cleaned_props: dict[str, Any] = {}
    for name, prop in props.items():
        if _is_json_dict(prop) and "observed" in prop:
            cleaned_props[name] = {k: v for k, v in prop.items() if k != "observed"}
        else:
            cleaned_props[name] = prop
    return {**schema, "properties": cleaned_props}


def _build_endpoint_summary(
    ep: EndpointSpec,
    all_traces: list[Trace],
    correlations: list[Correlation],
) -> dict[str, Any]:
    """Build a compact summary of one endpoint for the LLM prompt.

    Uses the annotated schemas already computed by mechanical extraction
    rather than raw trace bodies — cheaper in tokens and no information is
    lost to truncation.  All four schemas (path, query, body, response) are
    presented uniformly.
    """
    summary: dict[str, Any] = dict(
        id=ep.id,
        method=ep.method,
        path=ep.path,
    )

    # Find traces matching this endpoint (for correlation lookup only)
    ep_traces = _find_endpoint_traces(ep, all_traces)

    # Build UI trigger context from correlations
    ui_triggers: list[dict[str, str]] = []
    for corr in correlations:
        for t in corr.traces:
            if t in ep_traces:
                ui_triggers.append(
                    {
                        "action": corr.context.meta.action,
                        "element_text": corr.context.meta.element.text,
                        "page_url": corr.context.meta.page.url,
                    }
                )
                break
    if ui_triggers:
        summary["ui_triggers"] = ui_triggers[:3]

    # Strip root-level observed (redundant with property name/type);
    # nested observed are kept as useful context for the LLM.
    if ep.request.path_schema:
        summary["path_parameters"] = _strip_root_observed(ep.request.path_schema)
    if ep.request.query_schema:
        summary["query_parameters"] = _strip_root_observed(ep.request.query_schema)
    if ep.request.body_schema:
        summary["request_body"] = _strip_root_observed(ep.request.body_schema)

    # Response schemas (from mechanical extraction)
    if ep.responses:
        responses_list: list[dict[str, Any]] = []
        for resp in ep.responses:
            resp_info: dict[str, Any] = {"status": resp.status}
            if resp.content_type:
                resp_info["content_type"] = resp.content_type
            if resp.schema_:
                resp_info["schema"] = _strip_root_observed(resp.schema_)
            responses_list.append(resp_info)
        summary["responses"] = responses_list

    return summary


def _find_endpoint_traces(ep: EndpointSpec, traces: list[Trace]) -> list[Trace]:
    """Find traces that match this endpoint's method and path pattern."""
    pattern_re = pattern_to_regex(ep.path)
    matched: list[Trace] = []
    for t in traces:
        if t.meta.request.method.upper() != ep.method:
            continue
        parsed = urlparse(t.meta.request.url)
        if pattern_re.match(parsed.path):
            matched.append(t)
    return matched


def _is_json_dict(val: object) -> TypeGuard[dict[str, Any]]:
    """Type guard: parsed JSON dicts always have string keys."""
    return isinstance(val, dict)


def _apply_schema_descriptions(
    schema: dict[str, Any] | None, descriptions: dict[str, Any]
) -> None:
    """Write ``description`` into schema properties, matching by field name.

    Descriptions mirror the schema structure: leaf values (strings) are
    descriptions, intermediate values (dicts) recurse into nested properties
    or into array items.
    """
    if not schema or not descriptions:
        return
    props: dict[str, Any] = schema.get("properties", {})
    for field_name, desc in descriptions.items():
        if field_name not in props:
            continue
        if isinstance(desc, str):
            props[field_name]["description"] = desc
        elif _is_json_dict(desc):
            prop_schema = props[field_name]
            if prop_schema.get("type") == "array" and "items" in prop_schema:
                # Array of objects: descriptions apply to item properties
                _apply_schema_descriptions(prop_schema["items"], desc)
            else:
                # Nested object
                _apply_schema_descriptions(prop_schema, desc)


def _apply_enrichment(endpoint: EndpointSpec, enrich: dict[str, Any]) -> None:
    """Apply enrichment data from an LLM response to an endpoint."""
    if enrich.get("description"):
        endpoint.description = enrich["description"]
    if enrich.get("discovery_notes"):
        endpoint.discovery_notes = enrich["discovery_notes"]

    # Apply field descriptions from recursive structure
    field_descs = enrich.get("field_descriptions", {})
    if _is_json_dict(field_descs):
        path_descs = field_descs.get("path_parameters", {})
        if _is_json_dict(path_descs):
            _apply_schema_descriptions(endpoint.request.path_schema, path_descs)

        query_descs = field_descs.get("query_parameters", {})
        if _is_json_dict(query_descs):
            _apply_schema_descriptions(endpoint.request.query_schema, query_descs)

        body_descs = field_descs.get("request_body", {})
        if _is_json_dict(body_descs):
            _apply_schema_descriptions(endpoint.request.body_schema, body_descs)

        resp_descs = field_descs.get("responses", {})
        if _is_json_dict(resp_descs):
            for resp in endpoint.responses:
                status_descs = resp_descs.get(str(resp.status))
                if _is_json_dict(status_descs) and resp.schema_:
                    _apply_schema_descriptions(resp.schema_, status_descs)

    # Response details (business meaning, scenario, impact, resolution)
    response_details = enrich.get("response_details", {})
    if _is_json_dict(response_details) and response_details:
        for resp in endpoint.responses:
            detail = response_details.get(str(resp.status))
            if _is_json_dict(detail):
                if detail.get("business_meaning"):
                    resp.business_meaning = detail["business_meaning"]
                if detail.get("example_scenario"):
                    resp.example_scenario = detail["example_scenario"]
                if detail.get("user_impact"):
                    resp.user_impact = detail["user_impact"]
                if detail.get("resolution"):
                    resp.resolution = detail["resolution"]
            elif isinstance(detail, str):
                resp.business_meaning = detail
