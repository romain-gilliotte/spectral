# Errors and Operational Behavior

The enriched API spec records error patterns and operational characteristics observed during capture. Unlike API-first documentation where developers describe all possible errors and limits, reverse-engineered documentation can only report what was actually seen. This document describes how the format represents these observations and what generators can do with them.

---

## Error responses

Error responses (4xx, 5xx status codes) appear as `ResponseSpec` entries on the endpoint that returned them. They use the same structure as success responses, with additional fields that become especially relevant for errors.

### Fields relevant to errors

| Field | Purpose for errors |
|---|---|
| `status` | The HTTP status code observed (e.g. 403, 404, 422, 500) |
| `content_type` | Response content type (often `application/json` for structured errors) |
| `schema` | JSON Schema of the error body, inferred from observed error responses |
| `example_body` | An actual error response body from captured traffic |
| `business_meaning` | LLM-inferred explanation of why this error occurs in business terms |
| `example_scenario` | When this error was observed: "Customer with expired contract accessing consumption data" |
| `user_impact` | What happens to the user when this error occurs: "Cannot view consumption data" |
| `resolution` | How to recover: "Contact customer service to reactivate account" |

### What the LLM infers for errors

The LLM has three sources of information for understanding errors:

1. **The error response body itself.** Many APIs return structured error objects with messages, codes, and details. The LLM reads these to understand the error's nature.

2. **The UI context at the time of the error.** If the captured page showed an error message, alert banner, or redirect after the error response, the LLM can correlate the technical error with its user-visible consequence. This is unique to our approach — the LLM can say "this 403 causes a redirect to the login page with the message 'Your session has expired'" because it saw both the HTTP response and the page state.

3. **The business domain context.** The LLM understands what the endpoint does (from enrichment) and can infer plausible causes. A 403 on a consumption endpoint for an energy provider likely means the contract is inactive, not just "forbidden."

### Limitations of error documentation

Only errors that actually occurred during the capture session are documented. Common error scenarios that did not happen (invalid input validation, resource not found for non-existent IDs, server errors) will be absent.

The format does not distinguish between errors the user deliberately triggered and errors that occurred accidentally. A 404 might have been caused by navigating to a deleted resource or by a bug in the application.

Error schemas may be less reliable than success schemas because errors are typically observed fewer times. An error seen once produces a schema from a single sample — less robust than a success schema merged from twenty observations.

---

## Rate limiting

Rate limit information is captured mechanically from response headers when present.

### Detection

The pipeline examines response headers for standard rate limiting signals:

| Header | What it indicates |
|---|---|
| `X-RateLimit-Limit` | Maximum requests allowed in the current window |
| `X-RateLimit-Remaining` | Requests remaining in the current window |
| `X-RateLimit-Reset` | When the rate limit window resets (timestamp or seconds) |
| `Retry-After` | How long to wait before retrying (seconds or date) |
| `RateLimit-Limit` (IETF draft) | Same as X-RateLimit-Limit, standard draft format |
| `RateLimit-Remaining` | Same as X-RateLimit-Remaining, standard draft format |
| `RateLimit-Reset` | Same as X-RateLimit-Reset, standard draft format |

When rate limit headers are found, their values are recorded in the `rate_limit` field on the endpoint as a human-readable summary.

### Limitations

Rate limiting can only be documented if the response headers include rate limit information. Many APIs enforce rate limits without exposing them in headers. If the user never hit a rate limit during capture, no 429 responses will appear in the error list.

The format currently stores rate limit information as a free-text string on each endpoint. A future improvement could add structured rate limit fields (limit, window, policy) for generators to produce more precise documentation.

---

## Pagination

Pagination patterns are observed mechanically from request parameters and response structure.

### Detection signals

| Signal | Location | Pattern |
|---|---|---|
| Offset-based | Query parameters | `offset`, `skip`, `start` parameters with numeric values |
| Page-based | Query parameters | `page`, `page_number` parameters with incrementing values |
| Cursor-based | Query/body parameters | `cursor`, `after`, `before` parameters with opaque token values |
| Link headers | Response headers | `Link` header with `rel="next"`, `rel="prev"`, `rel="last"` |
| Response metadata | Response body | Fields like `total`, `count`, `has_more`, `next_cursor`, `next_page` |

When pagination parameters are detected, they appear as `ParameterSpec` entries on the endpoint with appropriate `business_meaning` (e.g. "Page number for paginated results") if the LLM enrichment identifies them.

Response body fields related to pagination (total count, next cursor, has_more flag) appear in the response schema and may receive `business_meaning` annotations from the LLM.

### Limitations

Pagination documentation depends on the user actually paginating during capture. If the user only viewed the first page of results, the spec will show the pagination parameters they used but may miss cursor-based patterns that only appear on subsequent pages.

The format does not have a dedicated pagination section — pagination is represented through parameter and response schema annotations on individual endpoints. A future improvement could add a structured pagination description per endpoint for generators to produce "how to paginate" guides.

---

## Caching

Cache-related headers are observed mechanically from responses.

### Detection signals

| Header | What it indicates |
|---|---|
| `Cache-Control` | Caching policy (max-age, no-cache, no-store, private, public) |
| `ETag` | Entity tag for conditional requests |
| `Last-Modified` | Last modification timestamp for conditional requests |
| `Expires` | Expiration date for cached responses |
| `Vary` | Which request headers affect caching |

These headers appear in the response data within `ResponseSpec`. The current format does not extract them into separate fields — they are part of the observed response headers available in the source traces.

### Target improvement

A future version could surface cache behavior as a structured annotation on each endpoint, enabling generators to produce caching guidance: "This endpoint supports conditional requests via ETag. Responses are cached for 5 minutes (Cache-Control: max-age=300)."

---

## Confidence levels

The format distinguishes between mechanical observations and LLM inferences across all sections documented above.

### The confidence spectrum

| Level | Meaning | Example |
|---|---|---|
| **Observed fact** | Directly extracted from captured traffic, no interpretation | Status code 403 was returned, response body contained `{"error": "contract_inactive"}` |
| **Mechanical inference** | Derived from observations through deterministic rules | Parameter is required (present in 100% of observed requests) |
| **LLM inference (high confidence)** | Strong correlation between UI context and API behavior | "This 403 occurs when the user's energy contract is inactive" (inferred from error body + UI alert) |
| **LLM inference (low confidence)** | Plausible interpretation without strong supporting evidence | "Retry after reactivating your contract" (reasonable advice but not directly observed) |

### How confidence is represented

The `correlation_confidence` field on each endpoint provides a numeric 0.0–1.0 score for the UI-to-API correlation. This is the only explicit confidence signal in the current format.

For other inferred fields (`business_meaning`, `user_impact`, `resolution`, `constraints`), confidence is implicit — they are either present (the LLM provided them) or null (the LLM did not). The quality of inference depends on how much supporting evidence was available: rich UI context with visible error messages produces higher-quality inference than API calls with no correlated UI action.

### Guidance for generators

Generators should treat the observed/inferred distinction as a presentation concern:

- **Observed facts** can be stated directly: "Returns status 403 with error body containing an error code and message."
- **High-confidence inferences** can be stated with mild qualification: "This typically occurs when the customer's contract is inactive."
- **Low-confidence inferences** should be hedged: "This may indicate that the account needs reactivation."
- **Absent fields** should be omitted, not filled with generic placeholders.

The `observed_count` on each endpoint provides additional context — an endpoint observed 20 times has more reliable error documentation than one observed once.
