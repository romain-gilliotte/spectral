# Analyze Stage — Objectives

The analyze stage transforms a raw capture bundle (network traces + UI actions) into a semantically-rich API specification. It is the core of what makes api-discover different from existing API documentation tools.

---

## Goal

Given a ZIP bundle of captured network traffic and UI context from a browsing session, produce a structured specification that describes not just the technical shape of each API endpoint, but its **business meaning**, the **user workflows** it supports, and the **domain vocabulary** of the application.

The output is the enriched API spec format described in [format/README.md](../format/README.md). All five generators (OpenAPI, MCP server, Python client, Markdown docs, cURL scripts) consume this single format.

---

## What makes this different

Most API documentation tools work from the inside out — they read source code, OpenAPI annotations, or framework metadata. HAR-based tools extract technical shapes (URLs, headers, status codes) but miss the "why."

api-discover works from the outside in: it observes the application as a user sees it, then correlates what the user did (clicked a button labeled "My Consumption") with what the network did (POST to `/api/consumption/monthly`). This correlation is what lets the LLM infer business purpose, user stories, and domain terminology that no purely mechanical tool can produce.

**Data sources available to the analysis pipeline:**

| Source | Nature | What it provides |
|---|---|---|
| Network traces | Mechanical, factual | URLs, methods, headers, request/response bodies, status codes, timing |
| UI context | Mechanical, factual | Page headings, navigation, form fields, button text, alerts, element selectors |
| Product documentation (in captured pages) | Factual, requires interpretation | Domain terminology, help text, error messages as displayed to users |
| LLM inference | Inferred, with confidence | Business purpose, user stories, correlations, glossary, workflow reconstruction |

The UI context and visible product documentation give the LLM far more to work with than raw traffic alone. It can adopt the application's own language, understand form labels and navigation structure, and reconstruct the user's journey through the product.

---

## Quality objectives

The enriched spec targets seven documentation quality principles (detailed in [format/principles.md](../format/principles.md)). Here is how the analyze stage contributes to each, honestly assessed for what reverse engineering can and cannot achieve.

| Principle | Analyze stage contribution | Realistic limitation |
|---|---|---|
| **Clear** | LLM generates business-language descriptions from UI context, not just technical endpoint names | Quality depends on how descriptive the captured UI text is |
| **Concise** | Batch enrichment produces focused descriptions; mechanical extraction avoids redundancy | LLM output quality varies — may over-explain or under-explain |
| **Contextual** | UI triggers link each endpoint to the user action that invoked it; workflows reconstruct the user journey | Only captures workflows the user actually performed during the session |
| **Complete** | Schemas inferred from all observed request/response bodies; auth detected from all traces | Cannot discover endpoints or error codes never triggered during capture |
| **Consistent** | Single batch LLM call sees all endpoints at once, producing consistent terminology and naming | Consistency depends on LLM adherence to its own patterns across the batch |
| **Concrete** | Observed values, example bodies, and real request/response pairs from actual traffic | Examples are real but may contain user-specific data that needs redaction |
| **Convenient** | Structured output feeds directly into generators for multiple output formats | The spec is a data format, not documentation itself — generators do the final presentation |

---

## Pipeline architecture

The analysis runs as a step-based pipeline with three parallel branches. Each step is a typed `Step[In, Out]` with typed input and output. Steps are either mechanical (deterministic data transformation) or LLM-based (with validation and retry).

See the full pipeline documentation:
- [Pipeline overview](./steps/00-overview.md) — architecture, step table, Mermaid diagram
- [Detect base URL](./steps/01-detect-base-url.md) — LLM identifies the business API origin
- [Group endpoints](./steps/02-group-endpoints.md) — LLM groups URLs into endpoint patterns
- [Mechanical extraction](./steps/03-mechanical-extraction.md) — schemas, parameters, UI triggers
- [Enrich + business context](./steps/04-enrich-and-context.md) — single LLM batch call
- [Auth analysis](./steps/05-auth-analysis.md) — parallel branch, all unfiltered traces
