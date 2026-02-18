"""Step: Enrich all endpoints + infer business context in a single LLM call."""

from __future__ import annotations

import json
from typing import Any, cast

from cli.analyze.steps.base import LLMStep
from cli.analyze.steps.types import EnrichmentContext, EnrichmentResult
from cli.analyze.tools import extract_json, save_debug
from cli.analyze.utils import truncate_json
from cli.formats.api_spec import BusinessContext, EndpointSpec, WorkflowStep


class EnrichAndContextStep(LLMStep[EnrichmentContext, EnrichmentResult]):
    """Single LLM call to enrich ALL endpoints with business semantics
    and infer overall business context + glossary.

    Replaces the previous N calls to analyze_endpoint_detail + 1 call to
    analyze_business_context with a single batch call.
    """

    name = "enrich_and_context"

    async def _execute(self, input: EnrichmentContext) -> EnrichmentResult:
        trace_map = {t.meta.id: t for t in input.traces}

        # Build compact summaries of all endpoints
        endpoint_summaries: list[dict[str, Any]] = []
        for ep in input.endpoints:
            summary: dict[str, Any] = dict(
                id=ep.id,
                method=ep.method,
                path=ep.path,
                observed_count=ep.observed_count,
            )

            # Add UI triggers
            if ep.ui_triggers:
                summary["ui_triggers"] = [
                    {
                        "action": t.action,
                        "element_text": t.element_text,
                        "page_url": t.page_url,
                    }
                    for t in ep.ui_triggers[:2]
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
                            json.loads(t.request_body), max_keys=8
                        )
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
                if t.response_body:
                    try:
                        summary["sample_response_body"] = truncate_json(
                            json.loads(t.response_body), max_keys=8
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

            # Add parameter names with observed values for constraint inference
            if ep.request.parameters:
                params_list: list[dict[str, Any]] = []
                for p in ep.request.parameters:
                    param_info: dict[str, Any] = dict(
                        name=p.name,
                        location=p.location,
                        type=p.type,
                    )
                    if p.observed_values:
                        param_info["observed_values"] = p.observed_values[:3]
                    params_list.append(param_info)
                summary["parameters"] = params_list

            endpoint_summaries.append(summary)

        # Build WS connection summaries
        ws_section = ""
        ws_ids: list[str] = []
        if input.ws_connections:
            ws_summaries: list[dict[str, Any]] = []
            for ws in input.ws_connections:
                ws_ids.append(ws.meta.id)
                ws_info: dict[str, Any] = dict(
                    id=ws.meta.id,
                    url=ws.meta.url,
                    message_count=len(ws.messages),
                )
                if ws.meta.protocols:
                    ws_info["protocols"] = ws.meta.protocols
                # Include a sample of message payloads
                msg_samples: list[dict[str, Any]] = []
                for msg in ws.messages[:3]:
                    if msg.payload:
                        try:
                            payload = json.loads(msg.payload)
                            msg_samples.append(
                                {
                                    "direction": msg.meta.direction,
                                    "payload": truncate_json(payload, max_keys=5),
                                }
                            )
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            pass
                if msg_samples:
                    ws_info["sample_messages"] = msg_samples
                ws_summaries.append(ws_info)
            ws_section = f"""

Also, these WebSocket connections were observed:

{json.dumps(ws_summaries, indent=1)[:3000]}
"""

        prompt = f"""You are analyzing API endpoints discovered from "{input.app_name}" ({input.base_url}).

Here are all the discovered endpoints with their mechanical data:

{json.dumps(endpoint_summaries, indent=1)[:12000]}
{ws_section}
Provide a SINGLE JSON response with {("three" if ws_ids else "two")} top-level keys:

1. "endpoints": an object keyed by endpoint ID, where each value has:
   - "business_purpose": concise description of what this endpoint does in business terms
   - "user_story": "As a [persona], I want to [action] so that [goal]"
   - "correlation_confidence": 0.0-1.0 confidence in the UI↔API correlation
   - "parameter_meanings": {{param_name: "business meaning"}} for each parameter
   - "parameter_constraints": {{param_name: "constraint text"}} for parameters where constraints can be inferred from observed values (or omit if none)
   - "response_details": {{status_code_string: {{"business_meaning": "...", "example_scenario": "...", "user_impact": "..." or null, "resolution": "..." or null}}}} for each observed status. For error statuses (4xx/5xx), include user_impact and resolution.
   - "trigger_explanations": array of natural language descriptions for each UI trigger
   - "discovery_notes": observations, edge cases, or dependencies worth noting about this endpoint (or null)

2. "business_context": an object with:
   - "api_name": a concise, descriptive name for this API (e.g., "Acme E-Commerce API")
   - "domain": the business domain (e.g., "E-commerce", "Project Management")
   - "description": a one-line description of this API
   - "user_personas": array of user types
   - "key_workflows": array of {{"name": "...", "description": "...", "steps": [...]}}
   - "business_glossary": {{term: "definition"}} for domain-specific terms
{('3. "websocket_purposes": an object keyed by WebSocket connection ID (' + ", ".join(f'"{wid}"' for wid in ws_ids) + "), where each value is a concise business_purpose string describing what this WebSocket connection is used for." if ws_ids else "")}
Respond in JSON."""

        response: Any = await self.client.messages.create(
            model=self.model,
            max_tokens=6144,
            messages=[{"role": "user", "content": prompt}],
        )

        save_debug(
            self.debug_dir, "enrich_and_context", prompt, response.content[0].text
        )
        data = extract_json(response.content[0].text)

        if not isinstance(data, dict):
            return EnrichmentResult(
                endpoints=input.endpoints,
                business_context=BusinessContext(),
                glossary={},
            )

        # Apply per-endpoint enrichments
        enrichments_raw: Any = data.get("endpoints", {})
        if isinstance(enrichments_raw, dict):
            enrichments_dict = cast(dict[str, Any], enrichments_raw)
            for ep in input.endpoints:
                enrich_raw: Any = enrichments_dict.get(ep.id, {})
                if not isinstance(enrich_raw, dict):
                    continue
                _apply_enrichment(ep, cast(dict[str, Any], enrich_raw))

        # Parse business context
        ctx_raw: Any = data.get("business_context", {})
        if not isinstance(ctx_raw, dict):
            ctx_raw = {}
        ctx_data = cast(dict[str, Any], ctx_raw)

        workflows: list[WorkflowStep] = []
        wf_list: Any = ctx_data.get("key_workflows", [])
        if isinstance(wf_list, list):
            for wf_raw_item in cast(list[Any], wf_list):
                if isinstance(wf_raw_item, dict):
                    wf = cast(dict[str, Any], wf_raw_item)
                    workflows.append(
                        WorkflowStep(
                            name=str(wf.get("name", "")),
                            description=str(wf.get("description", "")),
                            steps=wf.get("steps", []),
                        )
                    )

        business_context = BusinessContext(
            domain=str(ctx_data.get("domain", "")),
            description=str(ctx_data.get("description", "")),
            user_personas=ctx_data.get("user_personas", []),
            key_workflows=workflows,
        )

        glossary_raw: Any = ctx_data.get("business_glossary", {})
        glossary: dict[str, str] = {}
        if isinstance(glossary_raw, dict):
            glossary = cast(dict[str, str], glossary_raw)

        api_name_raw: Any = ctx_data.get("api_name")
        api_name: str | None = None
        if isinstance(api_name_raw, str) and api_name_raw.strip():
            api_name = api_name_raw

        ws_enrichments: dict[str, str] | None = None
        ws_raw: Any = data.get("websocket_purposes", {})
        if isinstance(ws_raw, dict):
            ws_dict = cast(dict[str, Any], ws_raw)
            # Filter to only string values
            ws_enrichments = {
                str(k): v for k, v in ws_dict.items() if isinstance(v, str)
            }
            if not ws_enrichments:
                ws_enrichments = None

        return EnrichmentResult(
            endpoints=input.endpoints,
            business_context=business_context,
            glossary=glossary,
            api_name=api_name,
            ws_enrichments=ws_enrichments,
        )


def _apply_enrichment(endpoint: EndpointSpec, enrich: dict[str, Any]) -> None:
    """Apply enrichment data from the batch LLM response to an endpoint."""
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
                # Tolerate flat string in response_details
                resp.business_meaning = detail_raw
    else:
        # Fallback to flat response_meanings format
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
