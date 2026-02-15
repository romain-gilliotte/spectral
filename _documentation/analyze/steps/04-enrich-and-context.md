# Step 4 — Enrich + Business Context

> `LLMStep[(list[EndpointSpec], str, str), (list[EndpointSpec], BusinessContext, dict)]`
>
> **In:** mechanical endpoint specs + app_name + base_url — **Out:** enriched endpoints + business context + glossary

[← Back to overview](./00-overview.md)

---

## Purpose

Single LLM call that enriches ALL endpoints with business semantics AND infers overall business context. Replaces the previous N+1 calls (N per-endpoint + 1 business context).

## Why one call instead of N+1

- The LLM sees all endpoints at once → better business context inference
- Cross-endpoint knowledge: consistent parameter naming, shared pattern detection
- Much fewer API calls (1 vs N+1), lower latency
- The mechanical schemas are already extracted, so the LLM input is structured and concise

## Input

For each mechanical endpoint, a summary containing:
- `method`, `pattern`, `observed_count`
- `request` annotated schema (params with observed values inline)
- `responses` by status code, each with annotated schema
- `ui_triggers` with action, element text, page URL

Plus global context: `app_name`, `base_url`

## Prompt

> "Here are all the endpoints discovered from this app, with their annotated schemas and UI triggers. For each endpoint, provide business_purpose, user_story, parameter_meanings, response_meanings, trigger_explanations, and identify enums from observed values. Also provide overall business_context (domain, personas, workflows) and business_glossary."

## Output

### Per endpoint

| Field | Description |
|---|---|
| `business_purpose` | What this endpoint does in business terms |
| `user_story` | "As a [persona], I want to [action] so that [goal]" |
| `correlation_confidence` | 0.0–1.0 confidence in UI↔API correlation |
| `parameter_meanings` | `{param_name: "business meaning"}` for each parameter |
| `response_meanings` | `{status_code: "business meaning"}` for each status |
| `trigger_explanations` | Natural language description for each UI trigger |
| `enum_fields` | Fields identified as enums from observed values (e.g. `status: ["active", "inactive"]`) |

### Overall

| Field | Description |
|---|---|
| `business_context.domain` | Business domain (e.g. "E-commerce", "Energy Management") |
| `business_context.description` | One-line description of the API |
| `business_context.user_personas` | Types of users (e.g. "residential_customer") |
| `business_context.key_workflows` | Reconstructed user workflows with steps |
| `business_glossary` | `{term: "definition"}` for domain-specific terms |

## Application

`_apply_enrichment` maps LLM output onto the mechanical endpoints:
- `endpoint.business_purpose` ← `enrichment.business_purpose`
- `endpoint.user_story` ← `enrichment.user_story`
- `endpoint.correlation_confidence` ← `enrichment.correlation_confidence`
- For each param: `param.business_meaning` ← `enrichment.parameter_meanings[param.name]`
- For each response: `resp.business_meaning` ← `enrichment.response_meanings[resp.status]`
- For each trigger by index: `trigger.user_explanation` ← `enrichment.trigger_explanations[i]`

## Configuration

| Parameter | Value |
|---|---|
| `max_tokens` | 4096 |
| Tools | None (direct `client.messages.create`) |

## Validation

Best-effort — `_validate_output` returns `[]`. Empty fields are acceptable. The pipeline continues with whatever the LLM provides.

## Fallback

Returns empty enrichments and empty `BusinessContext` on parse error.
