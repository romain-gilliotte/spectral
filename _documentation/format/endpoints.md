# Endpoint Specification

The endpoint specification (`EndpointSpec`) is the richest part of the enriched API spec. Each endpoint combines mechanical observations from captured traffic with LLM-inferred business semantics to produce a complete picture of what an API call does, why it exists, and how it relates to the user's experience.

This document covers all fields of `EndpointSpec`, organized by concern.

---

## Identity

These fields identify the endpoint and are all mechanically determined.

| Field | Type | Source | Description |
|---|---|---|---|
| `id` | string | Mechanical | Stable identifier derived from method and path (e.g. `get_monthly_consumption`) |
| `path` | string | LLM (grouping) | URL pattern with path parameters: `/api/users/{user_id}/orders` |
| `method` | string | Mechanical | HTTP method: GET, POST, PUT, PATCH, DELETE |

The `path` is produced during the endpoint grouping step, where the LLM identifies variable segments in observed URLs and replaces them with named parameters in `{param}` syntax. The base URL path prefix is stripped, so paths are relative to `protocols.rest.base_url`.

The `id` is generated from the method and path to be a valid identifier — useful for code generation (Python method names, OpenAPI operation IDs, MCP tool names).

---

## Business semantics

These fields are LLM-inferred from the combination of observed traffic, UI context, and page content. They represent what the endpoint means in business terms.

| Field | Type | Description |
|---|---|---|
| `business_purpose` | string or null | What the endpoint does in domain language. Should describe the business action, not the HTTP operation. |
| `user_story` | string or null | "As a [persona], I want to [action] so that [goal]" format. Connects the endpoint to a user need. |
| `correlation_confidence` | float (0.0–1.0) or null | How confident the LLM is in the link between UI action and API call. |
| `discovery_notes` | string or null | Free-form observations about the endpoint — patterns noticed, edge cases, dependencies on other endpoints. |

**Business purpose** should use the application's own vocabulary. For an energy provider, "Retrieve customer's monthly electricity consumption data" is better than "GET endpoint returning JSON." The LLM derives this from UI context (what tab or button triggered the call, what page the user was on) and response body content.

**User story** follows a standard format with inferred personas. It helps developers understand who benefits from this endpoint and why.

**Correlation confidence** ranges from high (the UI trigger clearly maps to this specific API call, with matching timing and context) to low (the API call happened during the session but its connection to a specific user action is unclear). Generators can use this to qualify descriptions — high-confidence endpoints can be described assertively, while low-confidence ones should note that the correlation is approximate.

---

## UI triggers

Each endpoint may have one or more UI triggers — user actions that were observed to cause this API call during the capture session.

| Field | Type | Source | Description |
|---|---|---|---|
| `action` | string | Mechanical | The type of user action: `click`, `input`, `submit`, `navigate` |
| `element_selector` | string | Mechanical | CSS selector of the interacted element |
| `element_text` | string | Mechanical | Visible text of the element (button label, link text, tab name) |
| `page_url` | string | Mechanical | URL of the page where the action occurred |
| `user_explanation` | string or null | LLM-inferred | Natural language description of what the user did and why |

The mechanical fields come directly from the capture bundle's UI context events, matched to API calls via time-window correlation. The `user_explanation` is the LLM's interpretation, synthesizing the element text, page context, and the resulting API call into a human-readable sentence.

UI triggers are what make the enriched spec unique — they let documentation say "this endpoint is called when the user clicks 'Export PDF' on the invoice detail page" rather than just documenting the HTTP interface in isolation.

An endpoint may have multiple triggers if different user actions lead to the same API call (e.g. a search endpoint triggered by both a search button click and a form submission). An endpoint may have no triggers if no UI action was correlated with it (background polling, prefetching, etc.).

---

## Request specification

The request section describes what the client sends.

### RequestSpec

| Field | Type | Description |
|---|---|---|
| `content_type` | string or null | Observed Content-Type header (e.g. `application/json`) |
| `parameters` | list of ParameterSpec | All discovered parameters across all locations |

### ParameterSpec

| Field | Type | Source | Description |
|---|---|---|---|
| `name` | string | Mechanical | Parameter name as it appears in the request |
| `location` | string | Mechanical | Where the parameter appears: `body`, `query`, `path`, `header` |
| `type` | string | Mechanical | Inferred JSON type: `string`, `number`, `boolean`, `array`, `object` |
| `format` | string or null | Mechanical | Detected format: `date`, `date-time`, `email`, `uuid`, `uri`, or null |
| `required` | boolean | Mechanical | True if present in every observed request for this endpoint |
| `business_meaning` | string or null | LLM-inferred | What the parameter represents in business terms |
| `example` | string or null | Mechanical | A representative observed value |
| `constraints` | string or null | LLM-inferred | Inferred constraints: "Cannot be future date," "max 100," "ISO country code" |
| `observed_values` | list of strings | Mechanical | Up to 5 distinct values observed in captured traffic |

**Parameter locations** are determined mechanically:
- **path** — segments identified as variable during endpoint grouping (e.g. the `{user_id}` in `/users/{user_id}`)
- **query** — URL query string parameters, extracted and deduplicated across all observed requests
- **body** — fields from request body JSON, with types inferred from observed values
- **header** — relevant request headers (Authorization, Content-Type, custom headers)

**Type inference** examines all observed values for each parameter and selects the most specific type that covers all observations. Format detection runs on string values to identify dates, emails, UUIDs, and URLs.

**Required** means the parameter was present in every observed request. This is a conservative heuristic — a parameter seen in 100% of 3 observations is less certainly required than one seen in 100% of 50 observations. The `observed_count` on the parent endpoint provides this context.

**Constraints** are LLM-inferred from observed values and business context. The LLM might notice that a date parameter never contains future dates, that a numeric parameter stays within a range, or that a string parameter follows a specific pattern. These are educated guesses, not guarantees.

---

## Response specification

Each endpoint has a list of `ResponseSpec` entries — one per observed HTTP status code.

| Field | Type | Source | Description |
|---|---|---|---|
| `status` | integer | Mechanical | HTTP status code |
| `content_type` | string or null | Mechanical | Observed Content-Type of the response |
| `business_meaning` | string or null | LLM-inferred | What this response means in business terms |
| `example_scenario` | string or null | LLM-inferred | When this response occurs, described as a real situation |
| `schema` | object or null | Mechanical | JSON Schema inferred from all observed response bodies with this status |
| `example_body` | any or null | Mechanical | A representative response body from captured traffic |
| `user_impact` | string or null | LLM-inferred | How this response affects the user's experience (primarily for errors) |
| `resolution` | string or null | LLM-inferred | How to recover from this response (primarily for errors) |

### Success responses

For 2xx responses, the schema is inferred by merging all observed response bodies. Properties present in every response are required; properties present in some are optional. The `example_body` is a real response body chosen as representative.

`business_meaning` for success responses explains what the returned data represents — "Monthly consumption breakdown with cost comparison to previous year" rather than "200 OK with JSON body."

`example_scenario` provides situational context — "Customer viewing January 2024 consumption after selecting the month from the date picker."

### Error responses

For 4xx and 5xx responses, additional fields become relevant. See [errors-and-operations.md](./errors-and-operations.md) for a detailed treatment of error handling in the format.

`user_impact` describes the consequence for the user — "Cannot view consumption data" or "Payment will not be processed."

`resolution` provides guidance on what to do — "Contact customer service to reactivate account" or "Retry with a valid date in YYYY-MM format." The LLM infers this from the error body content, the UI context (were error messages visible on the page?), and the business domain.

---

## Observability metadata

These fields provide evidence for the endpoint's existence and help consumers assess confidence.

| Field | Type | Source | Description |
|---|---|---|---|
| `observed_count` | integer | Mechanical | How many times this endpoint was called during capture |
| `source_trace_refs` | list of strings | Mechanical | IDs of the specific traces that matched this endpoint (e.g. `["t_0001", "t_0023"]`) |
| `requires_auth` | boolean | Mechanical | True if an Authorization header (or auth cookie) was observed in requests |
| `rate_limit` | string or null | Mechanical | Rate limit information if observed in response headers |

`observed_count` and `source_trace_refs` let consumers gauge how well-evidenced an endpoint is. An endpoint with one observation and a single trace reference is less reliable than one with twenty observations.

`requires_auth` is a mechanical detection based on the presence of authentication headers or cookies. It does not indicate whether the endpoint *would fail* without auth — only that auth was present when it was called.

`rate_limit` is populated if rate limiting headers (X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After, etc.) were observed in any response. See [errors-and-operations.md](./errors-and-operations.md) for details.
