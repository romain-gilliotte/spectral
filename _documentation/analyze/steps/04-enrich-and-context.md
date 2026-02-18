# Step 4 — Per-Endpoint Enrichment

> `LLMStep[EnrichmentContext, list[EndpointSpec]]`
>
> **In:** mechanical endpoint specs + traces + app_name + base_url — **Out:** enriched endpoints

[← Back to overview](./00-overview.md)

---

## Purpose

Parallel per-endpoint LLM calls that enrich each endpoint individually with business semantics. Each call is focused on a single endpoint, producing higher-quality enrichment than the previous single-batch approach.

## Why per-endpoint instead of batch

- Each call is focused — the LLM reasons about one endpoint at a time with full context
- Parallel execution via asyncio.gather — latency is roughly that of the slowest single call
- Failures are isolated — one endpoint failing doesn't affect the others
- Prompt is small and focused — less chance of the LLM losing track of instructions

## Input

For each endpoint, a summary containing:
- `method`, `path`, `observed_count`
- Up to 3 UI triggers with action, element text, page URL
- Sample request body and response body from the first trace
- All observed response status codes
- Parameters with observed values

Plus global context: `app_name`, `base_url` (included in each per-endpoint prompt).

## Prompt

Each per-endpoint call receives a prompt like:

> "You are analyzing a single API endpoint discovered from [app_name] ([base_url]). Here is the endpoint's mechanical data: [...]. Provide a JSON response with business_purpose, user_story, correlation_confidence, parameter_meanings, parameter_constraints, response_details, trigger_explanations, discovery_notes."

## Output

Per endpoint:

| Field | Description |
|---|---|
| `business_purpose` | What this endpoint does in business terms |
| `user_story` | "As a [persona], I want to [action] so that [goal]" |
| `correlation_confidence` | 0.0–1.0 confidence in UI↔API correlation |
| `parameter_meanings` | `{param_name: "business meaning"}` for each parameter |
| `parameter_constraints` | `{param_name: "constraint text"}` for parameters where constraints can be inferred |
| `response_details` | `{status_code: {business_meaning, example_scenario, user_impact, resolution}}` |
| `trigger_explanations` | Natural language description for each UI trigger |
| `discovery_notes` | Observations, edge cases, or dependencies worth noting |

## Application

`_apply_enrichment` maps each LLM response onto the corresponding endpoint:
- `endpoint.business_purpose` ← `enrichment.business_purpose`
- `endpoint.user_story` ← `enrichment.user_story`
- `endpoint.correlation_confidence` ← `enrichment.correlation_confidence`
- For each param: `param.business_meaning` ← `enrichment.parameter_meanings[param.name]`
- For each param: `param.constraints` ← `enrichment.parameter_constraints[param.name]`
- For each response: rich details from `enrichment.response_details[status]`
- For each trigger by index: `trigger.user_explanation` ← `enrichment.trigger_explanations[i]`

## Configuration

| Parameter | Value |
|---|---|
| `max_tokens` | 2048 per endpoint |
| Tools | None (direct `client.messages.create`) |
| Parallelism | All endpoints enriched concurrently via `asyncio.gather` |

## Validation

Best-effort — no validation on enrichment output. Empty fields are acceptable. The pipeline continues with whatever the LLM provides.

## Fallback

If a per-endpoint call fails (exception), the endpoint is left un-enriched. The pipeline continues with the mechanical data.
