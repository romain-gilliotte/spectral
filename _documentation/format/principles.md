# Documentation Principles — GitBook Alignment

This document maps the seven GitBook documentation quality principles to the enriched API spec format. For each principle, it describes what it means for API documentation, which format fields enable it, and where reverse engineering has honest limitations.

The principles come from GitBook's guides on API documentation best practices: clear, concise, contextual, complete, consistent, concrete, and convenient.

---

## 1. Clear

**Principle:** Documentation should be easy to understand by the target audience. Avoid jargon where possible; when domain-specific terms are necessary, define them.

**How the format enables it:**

The spec carries business-language descriptions at every level. `business_purpose` on each endpoint explains what it does in domain terms, not HTTP terms. `user_story` frames the endpoint from the user's perspective. `business_meaning` on parameters and responses explains their role in the business domain.

UI trigger explanations (`user_explanation`) describe what the user did in plain language — "User clicks on 'My Consumption' tab in the navigation" rather than "POST /api/consumption/monthly."

**Limitations:** Clarity depends on the quality of the captured UI text. If the application's own UI uses cryptic labels or abbreviations, the LLM has less context to produce clear descriptions. Applications in languages the LLM handles well produce better results than those in less-represented languages.

---

## 2. Concise

**Principle:** Say what needs to be said without unnecessary verbosity. Developers scan documentation — they need the essential information quickly.

**How the format enables it:**

The format separates structured data (schemas, parameters, status codes) from prose (business purpose, user story). Generators can present the structured parts as tables or parameter lists and reserve prose for the business context that adds value beyond the technical shape.

Annotated schemas include up to five observed values per property, giving developers a quick sense of what to expect without lengthy explanations. The `example_body` field provides a single representative example rather than exhaustive documentation of every possible response shape.

Per-endpoint enrichment (one focused LLM call per endpoint) produces concise descriptions because the LLM focuses on a single endpoint at a time without being overwhelmed by context from the full endpoint list.

**Limitations:** LLM-generated prose varies in conciseness. The enrichment prompt requests brief descriptions, but the LLM may sometimes over-explain simple endpoints or under-explain complex ones. This is a prompt-tuning concern, not a format limitation.

---

## 3. Contextual

**Principle:** Documentation should meet developers where they are. Provide context about when and why to use each endpoint, not just how.

**How the format enables it:**

This is the strongest principle for the enriched spec. UI triggers connect each endpoint to the user action that caused it — "This API call happens when the user clicks 'Export PDF' on the invoice page." No other API documentation tool provides this link between user interface and API behavior.

The `page_url` and page content captured with each UI context let the LLM understand what the user was looking at when the API call happened — form fields, navigation state, visible data, error messages.

**Limitations:** Contextual information is limited to workflows the user actually performed during the capture session. If a user only browsed their dashboard and never visited settings, the spec will have no context for settings-related endpoints. Multiple capture sessions can improve coverage, but the spec can only document what was observed.

---

## 4. Complete

**Principle:** Cover all endpoints, parameters, error codes, and edge cases. Don't leave developers guessing.

**How the format enables it:**

Schema inference merges all observed request and response bodies for each endpoint, building a union schema that captures every field seen across all samples. Optional fields (present in some responses but not all) are marked as such. Format detection identifies dates, emails, UUIDs, and URLs automatically.

Every response status code actually returned during capture gets its own `ResponseSpec` with schema, business meaning, and (for errors) user impact and resolution guidance.

Authentication is analyzed from ALL unfiltered traces — including requests to external identity providers that would be missed if only looking at the business API domain. This produces a complete picture of the auth flow, not just the token header.

Parameter discovery covers all locations: path parameters (from URL pattern grouping), query parameters, request body fields, and relevant headers.

**Limitations:** Completeness is fundamentally bounded by the capture session. Endpoints never called, error codes never triggered, and optional fields never returned will be absent. The spec cannot document rate limits that were never hit, pagination beyond what the user scrolled through, or webhook endpoints that receive inbound traffic.

The format does not claim completeness — `observed_count` and `source_trace_refs` make it transparent how much evidence backs each endpoint. An endpoint seen once with a single response status is clearly less complete than one seen twenty times with multiple status codes.

---

## 5. Consistent

**Principle:** Use the same terminology, formatting, and structure throughout. Developers build mental models from patterns — inconsistency breaks those models.

**How the format enables it:**

The format enforces structural consistency by design: every endpoint has the same set of fields (`id`, `path`, `method`, `business_purpose`, `user_story`, `request`, `responses`, etc.). Generators can rely on this uniform structure to produce consistent documentation pages.

**Limitations:** Per-endpoint enrichment may produce terminological inconsistencies — calling the same concept "billing period" in one endpoint and "invoice cycle" in another — since each call is independent. Future improvements could add a post-processing step to detect and reconcile such inconsistencies.

Structural consistency is guaranteed by the Pydantic models. Terminological consistency is best-effort.

---

## 6. Concrete

**Principle:** Provide real examples, not abstract descriptions. Show request/response pairs, working code snippets, and expected outputs.

**How the format enables it:**

Every piece of data in the spec comes from real traffic. `example_body` on responses contains an actual response body observed during capture. `observed_values` on parameters lists real values that were sent. `source_trace_refs` links back to the specific network traces that evidence each endpoint.

Request and response schemas are inferred from observed data, not written by hand. They reflect what the API actually does, not what its documentation claims.

UI triggers include the actual element text and page URL from the capture — concrete references to what the user saw and did.

The `example_scenario` field on each response provides a human-readable description of when that response was observed, such as "Customer viewing January 2024 consumption" — grounding the example in a real situation.

**Limitations:** Real examples from captured traffic may contain user-specific data (names, account numbers, tokens) that should be redacted before publishing. The format currently stores raw observed data; privacy-aware generation is a concern for the generators, not the spec format itself.

Examples are limited to what was captured. If the user only ever sent one type of request to an endpoint, the spec will have one example. Richer examples come from richer capture sessions.

---

## 7. Convenient

**Principle:** Make documentation easy to navigate, search, and use. Support the developer's workflow with quickstart guides, copy-paste examples, and logical organization.

**How the format enables it:**

The format is structured for multiple output generators. The same enriched spec produces OpenAPI (for tooling integration), a Python client (for immediate programmatic use), cURL scripts (for quick testing), Markdown docs (for reading), and an MCP server scaffold (for AI agent integration).

UI triggers provide natural groupings for a quickstart guide — developers can identify the most common user journeys from the trigger data.

The flat endpoint list with `id` fields enables generators to create deep links, cross-references, and table-of-contents navigation. The `requires_auth` flag on each endpoint lets generators clearly separate authenticated and unauthenticated endpoints.

**Target improvements:**

- **Quickstart section.** A future addition to the spec: the LLM identifies the simplest observed endpoint and produces a minimal quickstart guide — first call to try, minimal auth setup, expected result shape.
- **Resource groups.** A future addition where the LLM groups endpoints by domain resource (users, invoices, consumption) for navigable documentation structure. Currently, endpoints are a flat list; generators must impose their own grouping.

**Limitations:** Convenience is ultimately a property of the generated documentation, not the spec format. The format provides the building blocks — structured data, business context, examples, workflows — but the generators are responsible for assembling them into a convenient reading experience. The spec cannot anticipate every developer's workflow or tool preference, which is why it supports multiple output formats.
