# Enriched API Spec Format — Overview

The enriched API spec is the central data format of api-discover. It is the output of the `analyze` command and the input to all `generate` commands. Everything the pipeline discovers — technical shape, business meaning, user workflows, authentication, domain vocabulary — is captured in a single JSON document.

---

## Why a custom format

OpenAPI is the standard for API specifications, and api-discover generates OpenAPI as one of its outputs. But OpenAPI was designed for API-first documentation written by the API's own developers. It lacks constructs for several things that reverse engineering from captured traffic uniquely provides:

- **UI correlation.** Which user action triggered which API call, and what the user saw on screen when it happened. OpenAPI has no concept of UI triggers, page context, or element selectors.
- **Business semantics beyond descriptions.** User stories, domain glossary, workflow reconstruction, persona identification. OpenAPI has `description` and `summary` fields, but no structured representation of business context.
- **Multi-protocol support.** A single capture session may include REST endpoints, WebSocket connections, and (in the future) GraphQL or gRPC. OpenAPI covers REST only.
- **Observed evidence.** Every claim in the spec is backed by observed traffic — trace references, observed value lists, example bodies from real requests. OpenAPI examples are author-provided, not evidence-based.
- **Confidence levels.** LLM-inferred fields carry a confidence signal. Mechanical extractions are factual. This distinction matters when generating documentation — a high-confidence business purpose can be stated as fact, while a low-confidence one should be hedged.

The enriched spec is not a replacement for OpenAPI — it is a richer intermediate representation that *generates* OpenAPI (and four other output formats) as one of its consumers.

---

## Observed vs. inferred

Every field in the spec falls into one of two primary categories, though some fields (especially in authentication) combine both sources and are noted as "Mixed":

| Category | Source | Certainty | Examples |
|---|---|---|---|
| **Observed** (mechanical) | Directly extracted from captured traffic or UI context | Factual — matches what happened | URLs, methods, status codes, headers, request/response bodies, schemas, UI element text, page headings |
| **Inferred** (LLM) | Interpreted by the LLM from observed data + UI context | Probabilistic — may be wrong | Business purpose, user stories, parameter meanings, glossary terms, workflow reconstruction, correlation confidence |

This distinction runs through the entire format. Fields like `business_purpose`, `user_story`, `business_meaning`, `constraints`, `user_explanation`, and `correlation_confidence` are LLM-inferred. Fields like `path`, `method`, `schema`, `observed_values`, `status`, and `source_trace_refs` are mechanical observations.

Generators should treat these categories differently. Observed fields can be stated as fact. Inferred fields should be presented with appropriate confidence — especially when `correlation_confidence` is below a threshold.

---

## How the format is consumed

Five generators currently consume the enriched spec:

| Generator | Output | What it uses most |
|---|---|---|
| **OpenAPI** | OpenAPI 3.1 YAML | Endpoints, schemas, parameters, auth, base URL |
| **Python client** | Typed Python SDK | Endpoints, auth (login/refresh configs), parameter types |
| **Markdown docs** | Human-readable documentation | Everything — business context, glossary, user stories, workflows, auth journey |
| **cURL scripts** | Ready-to-use shell scripts | Endpoints, example bodies, auth headers |
| **MCP server** | FastMCP scaffold | Endpoints, parameter specs, business purpose (for tool descriptions) |

The Markdown docs generator is the richest consumer — it uses business context, glossary, user stories, UI triggers, and error resolution guidance to produce documentation that follows the principles described in [principles.md](./principles.md).

---

## Format documentation

| Document | Contents |
|---|---|
| [principles.md](./principles.md) | How the format supports the 7 GitBook documentation principles |
| [structure.md](./structure.md) | Top-level ApiSpec structure and all root-level sections |
| [endpoints.md](./endpoints.md) | Endpoint specification deep dive — the richest part of the format |
| [authentication.md](./authentication.md) | Auth specification — types, detection, login/refresh, user journey |
| [errors-and-operations.md](./errors-and-operations.md) | Error patterns, rate limiting, pagination, caching, confidence levels |

See also the [analyze stage documentation](../analyze/README.md) for how the pipeline produces this format.
