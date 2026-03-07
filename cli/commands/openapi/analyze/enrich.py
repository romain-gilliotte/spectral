"""Enrich endpoints with business semantics via parallel per-endpoint LLM calls."""

from __future__ import annotations

import asyncio
from typing import Any, TypeGuard

from cli.commands.capture.types import Trace
from cli.commands.openapi.analyze.extraction import match_traces_by_pattern
from cli.commands.openapi.analyze.types import (
    EndpointEnrichmentResponse,
    EndpointSpec,
    EnrichmentContext,
)
from cli.helpers.console import console
from cli.helpers.correlator import Correlation
from cli.helpers.json import minified
import cli.helpers.llm as llm

_MAX_SUMMARY_CHARS = 40_000
_MAX_RESPONSE_SCHEMA_CHARS = 5_000


async def enrich_endpoints(ctx: EnrichmentContext) -> list[EndpointSpec]:
    """Parallel per-endpoint LLM calls to enrich each endpoint with business semantics."""

    async def _enrich_one(ep: EndpointSpec) -> None:
        summary = _build_endpoint_summary(ep, ctx.traces, ctx.correlations)
        summary_json = minified(summary)
        if len(summary_json) > _MAX_SUMMARY_CHARS:
            est_tokens = len(summary_json) // 4
            console.print(
                f"  [yellow]Skipping enrichment for {ep.method} {ep.path}: "
                f"summary too large ({len(summary_json):,} chars, ~{est_tokens:,} tokens)[/yellow]"
            )
            return
        prompt = f"""You are analyzing a single API endpoint discovered from "{ctx.app_name}" ({ctx.base_url}).

Below is the endpoint's mechanical data as JSON Schema. Nested properties carry an "examples" array with sample values seen in real traffic — use these to understand business meaning.

{summary_json}

Provide a JSON response with these keys:
- "description": concise description of what this endpoint does in business terms (this becomes the OpenAPI summary)
- "field_descriptions": an object mirroring the schema structure with business descriptions for each field. Sub-keys:
  - "path_parameters": {{param_name: "description", ...}} (omit if no path parameters)
  - "query_parameters": {{param_name: "description", ...}} (omit if no query parameters)
  - "request_body": object mirroring the request body schema structure (omit if no request body)
  - "responses": {{status_code_string: object mirroring the response schema structure}} (omit if no response schemas; response schemas may be omitted for large endpoints — skip field_descriptions.responses for those statuses)
  Rules for field_descriptions structure:
  - Leaf values are always description strings.
  - Nested objects mirror the nesting: {{"address": {{"city": "...", "zip": "..."}}}}
  - For arrays of objects, use the array field name as key with a flat object describing the item properties: {{"items": {{"name": "...", "price": "..."}}}}
  - NEVER use dot-paths or bracket notation like "items[].name". Always use nested objects.
- "response_details": {{status_code_string: {{"business_meaning": "...", "example_scenario": "...", "user_impact": "..." or null, "resolution": "..." or null}}}} for each observed status. For error statuses (4xx/5xx), include user_impact and resolution.
- "discovery_notes": observations, edge cases, or dependencies worth noting about this endpoint (or null)

"""

        try:
            conv = llm.Conversation(max_tokens=4096, label=f"enrich_{ep.id}")
            result = await conv.ask_json(prompt, EndpointEnrichmentResponse)
            _apply_enrichment(ep, result)
        except Exception as exc:
            console.print(
                f"  [red]Enrichment failed for {ep.method} {ep.path}: "
                f"{type(exc).__name__}[/red]"
            )

    await asyncio.gather(*[_enrich_one(ep) for ep in ctx.endpoints])

    return ctx.endpoints



def _build_endpoint_summary(
    ep: EndpointSpec,
    all_traces: list[Trace],
    correlations: list[Correlation],
) -> dict[str, Any]:
    """Build a compact summary of one endpoint for the LLM prompt."""
    summary: dict[str, Any] = dict(
        id=ep.id,
        method=ep.method,
        path=ep.path,
    )

    ep_traces = match_traces_by_pattern(ep.method, ep.path, all_traces)

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

    if ep.request.path_schema:
        summary["path_parameters"] = ep.request.path_schema
    if ep.request.query_schema:
        summary["query_parameters"] = ep.request.query_schema
    if ep.request.body_schema:
        summary["request_body"] = ep.request.body_schema

    if ep.responses:
        responses_list: list[dict[str, Any]] = []
        for resp in ep.responses:
            resp_info: dict[str, Any] = {"status": resp.status}
            if resp.content_type:
                resp_info["content_type"] = resp.content_type
            if resp.schema_:
                serialized = minified(resp.schema_)
                if len(serialized) <= _MAX_RESPONSE_SCHEMA_CHARS:
                    resp_info["schema"] = resp.schema_
                else:
                    console.print(
                        f"  [yellow]Trimming response {resp.status} schema from "
                        f"enrichment for {ep.method} {ep.path} "
                        f"({len(serialized):,} chars)[/yellow]"
                    )
            responses_list.append(resp_info)
        summary["responses"] = responses_list

    return summary


def _is_json_dict(val: object) -> TypeGuard[dict[str, Any]]:
    """Type guard: parsed JSON dicts always have string keys."""
    return isinstance(val, dict)


def _apply_schema_descriptions(
    schema: dict[str, Any] | None, descriptions: dict[str, Any]
) -> None:
    """Write ``description`` into schema properties, matching by field name."""
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
                _apply_schema_descriptions(prop_schema["items"], desc)
            elif _is_json_dict(prop_schema.get("additionalProperties")):
                _apply_schema_descriptions(prop_schema["additionalProperties"], desc)
            else:
                _apply_schema_descriptions(prop_schema, desc)


def _apply_enrichment(endpoint: EndpointSpec, enrich: EndpointEnrichmentResponse) -> None:
    """Apply enrichment data from an LLM response to an endpoint."""
    if enrich.description:
        endpoint.description = enrich.description
    if enrich.discovery_notes:
        endpoint.discovery_notes = enrich.discovery_notes

    field_descs = enrich.field_descriptions or {}
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

    if enrich.response_details:
        for resp in endpoint.responses:
            detail = enrich.response_details.get(str(resp.status))
            if detail is not None:
                if detail.business_meaning:
                    resp.business_meaning = detail.business_meaning
                if detail.example_scenario:
                    resp.example_scenario = detail.example_scenario
                if detail.user_impact:
                    resp.user_impact = detail.user_impact
                if detail.resolution:
                    resp.resolution = detail.resolution
