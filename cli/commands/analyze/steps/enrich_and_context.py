"""Step: Enrich endpoints with business semantics via parallel per-endpoint LLM calls."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from cli.commands.analyze.steps.base import LLMStep
from cli.commands.analyze.steps.types import EnrichmentContext
from cli.commands.analyze.tools import extract_json, save_debug
from cli.commands.analyze.utils import truncate_json
from cli.formats.api_spec import EndpointSpec


class EnrichEndpointsStep(LLMStep[EnrichmentContext, list[EndpointSpec]]):
    """Parallel per-endpoint LLM calls to enrich each endpoint with business
    semantics: business_purpose, user_story, parameter meanings, response
    details, trigger explanations, and discovery notes.
    """

    name = "enrich_endpoints"

    async def _execute(self, input: EnrichmentContext) -> list[EndpointSpec]:
        trace_map = {t.meta.id: t for t in input.traces}

        async def _enrich_one(ep: EndpointSpec) -> None:
            summary = _build_endpoint_summary(ep, trace_map)
            prompt = f"""You are analyzing a single API endpoint discovered from "{input.app_name}" ({input.base_url}).

Here is the endpoint's mechanical data:

{json.dumps(summary, indent=1)[:6000]}

Provide a JSON response with these keys:
- "business_purpose": concise description of what this endpoint does in business terms
- "user_story": "As a [persona], I want to [action] so that [goal]"
- "correlation_confidence": 0.0-1.0 confidence in the UI↔API correlation
- "parameter_meanings": {{param_name: "business meaning"}} for each parameter
- "parameter_constraints": {{param_name: "constraint text"}} for parameters where constraints can be inferred from observed values (or omit if none)
- "response_details": {{status_code_string: {{"business_meaning": "...", "example_scenario": "...", "user_impact": "..." or null, "resolution": "..." or null}}}} for each observed status. For error statuses (4xx/5xx), include user_impact and resolution.
- "trigger_explanations": array of natural language descriptions for each UI trigger
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
                    _apply_enrichment(ep, cast(dict[str, Any], data))
            except Exception:
                pass  # Leave endpoint un-enriched on failure

        await asyncio.gather(*[_enrich_one(ep) for ep in input.endpoints])

        return input.endpoints


def _build_endpoint_summary(
    ep: EndpointSpec, trace_map: dict[str, Any]
) -> dict[str, Any]:
    """Build a compact summary of one endpoint for the LLM prompt."""
    summary: dict[str, Any] = dict(
        id=ep.id,
        method=ep.method,
        path=ep.path,
        observed_count=ep.observed_count,
    )

    if ep.ui_triggers:
        summary["ui_triggers"] = [
            {
                "action": t.action,
                "element_text": t.element_text,
                "page_url": t.page_url,
            }
            for t in ep.ui_triggers[:3]
        ]

    # Add sample request/response from first trace
    ep_traces = [
        trace_map[ref] for ref in ep.source_trace_refs[:2] if ref in trace_map
    ]
    if ep_traces:
        t = ep_traces[0]
        if t.request_body:
            try:
                summary["sample_request_body"] = truncate_json(
                    json.loads(t.request_body), max_keys=10
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        if t.response_body:
            try:
                summary["sample_response_body"] = truncate_json(
                    json.loads(t.response_body), max_keys=10
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        summary["response_statuses"] = list(
            set(
                trace_map[ref].meta.response.status
                for ref in ep.source_trace_refs
                if ref in trace_map
            )
        )

    if ep.request.parameters:
        params_list: list[dict[str, Any]] = []
        for p in ep.request.parameters:
            param_info: dict[str, Any] = dict(
                name=p.name,
                location=p.location,
                type=p.type,
            )
            if p.observed_values:
                param_info["observed_values"] = p.observed_values[:5]
            params_list.append(param_info)
        summary["parameters"] = params_list

    return summary


def _apply_enrichment(endpoint: EndpointSpec, enrich: dict[str, Any]) -> None:
    """Apply enrichment data from an LLM response to an endpoint."""
    if enrich.get("business_purpose"):
        endpoint.business_purpose = enrich["business_purpose"]
    if enrich.get("user_story"):
        endpoint.user_story = enrich["user_story"]
    if enrich.get("discovery_notes"):
        endpoint.discovery_notes = enrich["discovery_notes"]

    conf: Any = enrich.get("correlation_confidence")
    if conf is not None:
        try:
            endpoint.correlation_confidence = float(conf)
        except (ValueError, TypeError):
            pass

    param_meanings: Any = enrich.get("parameter_meanings", {})
    if isinstance(param_meanings, dict):
        for param in endpoint.request.parameters:
            if param.name in param_meanings:
                param.business_meaning = param_meanings[param.name]

    param_constraints: Any = enrich.get("parameter_constraints", {})
    if isinstance(param_constraints, dict):
        for param in endpoint.request.parameters:
            if param.name in param_constraints:
                param.constraints = param_constraints[param.name]

    # Support both rich response_details and flat response_meanings
    response_details_raw: Any = enrich.get("response_details", {})
    if isinstance(response_details_raw, dict) and response_details_raw:
        rd = cast(dict[str, Any], response_details_raw)
        for resp in endpoint.responses:
            key = str(resp.status)
            detail_raw: Any = rd.get(key)
            if isinstance(detail_raw, dict):
                detail = cast(dict[str, Any], detail_raw)
                if detail.get("business_meaning"):
                    resp.business_meaning = detail["business_meaning"]
                if detail.get("example_scenario"):
                    resp.example_scenario = detail["example_scenario"]
                if detail.get("user_impact"):
                    resp.user_impact = detail["user_impact"]
                if detail.get("resolution"):
                    resp.resolution = detail["resolution"]
            elif isinstance(detail_raw, str):
                resp.business_meaning = detail_raw
    else:
        response_meanings_raw: Any = enrich.get("response_meanings", {})
        if isinstance(response_meanings_raw, dict):
            rm = cast(dict[str, Any], response_meanings_raw)
            for resp in endpoint.responses:
                key = str(resp.status)
                if key in rm:
                    resp.business_meaning = rm[key]

    trigger_explanations_raw: Any = enrich.get("trigger_explanations", [])
    if isinstance(trigger_explanations_raw, list):
        trigger_explanations = cast(list[Any], trigger_explanations_raw)
        for i, trigger in enumerate(endpoint.ui_triggers):
            if i < len(trigger_explanations):
                trigger.user_explanation = trigger_explanations[i]
