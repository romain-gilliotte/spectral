# Top-Level Structure

The enriched API spec (`ApiSpec`) is a single JSON document with a flat top-level structure. Each section serves a distinct purpose, and generators pick the sections they need.

This document describes the root-level sections. For deep dives into specific parts, see [endpoints.md](./endpoints.md), [authentication.md](./authentication.md), and [errors-and-operations.md](./errors-and-operations.md).

---

## Root fields

| Field | Type | Source | Purpose |
|---|---|---|---|
| `api_spec_version` | string | Mechanical | Format version (semver). Currently `"1.0.0"`. |
| `name` | string | LLM-inferred | Human-readable name for the API (e.g. "EDF Customer Portal API") |
| `discovery_date` | string (ISO 8601) | Mechanical | When the analysis was performed |
| `source_captures` | list of strings | Mechanical | Filenames of the capture bundles that produced this spec |
| `business_context` | object | LLM-inferred | Domain, personas, workflows — see below |
| `auth` | object | Mixed | Authentication mechanism — see [authentication.md](./authentication.md) |
| `protocols` | object | Mixed | REST endpoints and WebSocket connections — see below |
| `business_glossary` | dict (term → definition) | LLM-inferred | Domain-specific vocabulary extracted from UI text and API field names |

---

## Metadata section

The metadata fields (`api_spec_version`, `name`, `discovery_date`, `source_captures`) identify the spec and its provenance. `source_captures` lists every capture bundle that contributed data, supporting future bundle-merging where multiple sessions for the same application are combined into a single spec.

The `name` field is inferred by the LLM from the application's title, visible branding, and the nature of the discovered endpoints. It should read as a natural name a developer would recognize — "Stripe Payment API," not "api.stripe.com REST endpoints."

---

## Business context

The `business_context` section captures domain-level understanding that applies across all endpoints.

| Field | Type | Description |
|---|---|---|
| `domain` | string | The business domain: "E-commerce," "Energy Management," "Healthcare," etc. |
| `description` | string | One-line description of what this API serves |
| `user_personas` | list of strings | Types of users observed: "residential_customer," "admin," "merchant" |
| `key_workflows` | list of WorkflowStep | Reconstructed user journeys through the application |

**WorkflowStep** describes a sequence of actions the user performed that the LLM has identified as a coherent workflow:

| Field | Type | Description |
|---|---|---|
| `name` | string | Workflow identifier (e.g. "view_consumption") |
| `description` | string | What the user accomplished |
| `steps` | list of strings | Ordered step names referencing endpoint IDs or UI actions |

Workflows are reconstructed from the timeline of UI actions and correlated API calls. They represent what the user actually did during the capture session, not hypothetical use cases.

---

## Business glossary

A flat dictionary mapping domain terms to their definitions. The LLM extracts these from visible page content (headings, navigation labels, form fields, help text) and API field names.

Terms should be specific to the application's domain — "PDL" (Point de Livraison) for an energy provider, "SKU" for an e-commerce platform. Generic API terms (endpoint, request, response) do not belong here.

Generators use the glossary to produce a dedicated glossary page and can optionally add inline definitions when domain terms appear in endpoint descriptions.

---

## Quickstart (target)

A planned addition to the top-level structure. Not yet implemented in the format or pipeline.

The quickstart section would contain the LLM's recommendation for the simplest way to start using the API, based on observed traffic:

| Target field | Purpose |
|---|---|
| `first_endpoint` | The simplest observed endpoint — low parameter count, no complex auth, common use case |
| `minimal_auth` | Minimum authentication needed for the first endpoint (may be "none" for public endpoints) |
| `expected_result` | What the developer should see — a summary of the typical response shape |
| `prerequisites` | What the developer needs before starting (API key, account, etc.) |
| `next_steps` | Suggested endpoints to try after the first one, building toward a real workflow |

The LLM would select the first endpoint by weighing simplicity (few parameters, GET preferred over POST), frequency (commonly called), and pedagogical value (representative of the API's purpose). This is inherently opinionated — the LLM makes a judgment call about the best entry point.

---

## Protocols

The `protocols` section contains the technical API specifications, organized by protocol type.

### REST

| Field | Type | Description |
|---|---|---|
| `base_url` | string | The business API base URL detected during analysis |
| `endpoints` | list of EndpointSpec | All discovered REST endpoints — see [endpoints.md](./endpoints.md) |

The `base_url` is the common prefix for all REST endpoint paths. It is detected by the LLM during analysis, filtering out CDN, analytics, and tracker domains. It may include a path prefix (e.g. `https://api.example.com/v2`).

Endpoints are currently a flat list ordered by the pipeline. See the resource groups target below for planned hierarchical organization.

### WebSocket

| Field | Type | Description |
|---|---|---|
| `connections` | list of WsConnectionSpec | Discovered WebSocket connections |

Each connection describes a WebSocket URL, its sub-protocol (if any), the observed messages in both directions, and LLM-inferred business purpose. Message schemas are mechanically inferred from observed payloads.

### Future protocols

The `protocols` structure is designed to accommodate additional protocol types as they are implemented:

- **GraphQL** — query/mutation/subscription extraction from observed operations
- **gRPC** — service/method extraction from observed protocol buffer traffic

Each would be a new key under `protocols` with its own type-specific structure.

---

## Resource groups (target)

A planned addition to the REST protocol section. Not yet implemented.

Currently, endpoints are a flat list. For applications with many endpoints, this produces documentation that is hard to navigate. Resource groups would let the LLM organize endpoints into logical categories based on the domain:

| Target field | Purpose |
|---|---|
| `resource_groups` | List of groups, each with a name, description, and list of endpoint IDs |

For example, an e-commerce API might have groups like "Products," "Orders," "Customers," and "Payments." An energy provider might have "Consumption," "Billing," "Contract," and "Account."

The LLM would infer these groups from endpoint path patterns, business purpose, and UI navigation structure (tabs, menu sections). The grouping serves documentation navigation — it does not change the endpoint data itself.

Generators would use resource groups to create a navigable table of contents, section headers, and sidebar navigation in the Markdown docs output.
