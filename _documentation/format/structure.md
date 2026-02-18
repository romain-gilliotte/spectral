# Top-Level Structure

The enriched API spec (`ApiSpec`) is a single JSON document with a flat top-level structure. Each section serves a distinct purpose, and generators pick the sections they need.

This document describes the root-level sections. For deep dives into specific parts, see [endpoints.md](./endpoints.md), [authentication.md](./authentication.md), and [errors-and-operations.md](./errors-and-operations.md).

---

## Root fields

| Field | Type | Source | Purpose |
|---|---|---|---|
| `api_spec_version` | string | Mechanical | Format version (semver). Currently `"1.0.0"`. |
| `name` | string | Mechanical | Human-readable name for the API, derived from the app name in the capture bundle |
| `discovery_date` | string (ISO 8601) | Mechanical | When the analysis was performed |
| `source_captures` | list of strings | Mechanical | Filenames of the capture bundles that produced this spec |
| `auth` | object | Mixed | Authentication mechanism — see [authentication.md](./authentication.md) |
| `protocols` | object | Mixed | REST endpoints and WebSocket connections — see below |

---

## Metadata section

The metadata fields (`api_spec_version`, `name`, `discovery_date`, `source_captures`) identify the spec and its provenance. `source_captures` lists every capture bundle that contributed data, supporting future bundle-merging where multiple sessions for the same application are combined into a single spec.

The `name` field is derived from the application name in the capture bundle manifest (e.g. "Test App" becomes "Test App API").

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
