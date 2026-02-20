# Pipeline overview

The `spectral analyze` command runs a multi-step pipeline that transforms a raw capture bundle into structured API specifications. The pipeline auto-detects the protocol (REST, GraphQL, or both) and processes each branch independently.

## Architecture

The pipeline is built on a typed step abstraction. Each step takes a typed input and produces a typed output, with optional validation and retry logic.

| Step type | Behavior on failure |
|-----------|-------------------|
| Mechanical step | Fails immediately — a validation error indicates a bug |
| LLM step | Retries once, appending the validation error to the conversation so the LLM can correct itself |

## Pipeline stages

### Stage 1: Preparation (sequential)

These steps run in order on the full set of traces:

1. **Extract pairs** — Collect all observed (method, URL) pairs from the traces. This is a mechanical step that simply reads the trace metadata.

2. **Detect base URL** — The LLM identifies the business API origin. It sees all unique URLs with their call frequency and uses investigation tools (base64 decode, URL decode, JWT decode) to inspect opaque values. This filters out CDN, analytics, and tracker domains that would pollute the spec.

3. **Filter traces** — Keep only the traces whose URL matches the detected base URL. Traces from other domains (analytics, CDN, third-party scripts) are discarded.

4. **Protocol split** — Separate the remaining traces into REST and GraphQL groups based on request shape (content type, query field presence, operation patterns).

### Stage 2: Extraction and enrichment (parallel)

The REST and GraphQL branches run concurrently via `asyncio.gather`. Auth analysis also runs in parallel with both branches.

#### REST branch

1. **Group endpoints** — The LLM groups URLs into endpoint patterns with `{param}` syntax. It sees all URLs for each method and identifies which path segments are variable (IDs, UUIDs, hashes). Investigation tools are available here too.

2. **Strip prefix** — Remove the base URL's path prefix from all patterns (e.g., `/api/v1/users/{id}` becomes `/users/{id}` if the base URL is `https://example.com/api/v1`).

3. **Mechanical extraction** — For each endpoint group, build the full endpoint specification: request/response schemas (inferred from observed JSON bodies), path/query parameters, headers, and status codes.

4. **Enrich endpoints** — N parallel LLM calls, one per endpoint. Each call receives the full mechanical data for one endpoint (schemas with observed values, all request/response examples) and produces business descriptions: operation summary, parameter meanings, response explanations. Failures are isolated — one endpoint failing does not affect others.

#### GraphQL branch

1. **Extraction** — Parse all GraphQL queries using `graphql-core` and walk the parsed field tree alongside the JSON response data. When `__typename` is present in responses, the step reconstructs explicit object types. Without `__typename`, types are inferred from response shapes (less precise). The result is a TypeRegistry containing object types, input types, enums, scalars, and field metadata (nullability, list cardinality).

2. **Enrich types** — N parallel LLM calls, one per type. Each call receives the type's fields with their observed values and produces descriptions for the type and each field.

#### Auth analysis

Runs concurrently with both branches. The LLM examines **all** unfiltered traces (not just those matching the base URL) to detect the authentication mechanism. This is important because auth providers often live on different domains (Auth0, Okta, Cognito, Google accounts).

### Stage 3: Assembly (sequential)

Each branch assembles its final output independently:

- **REST** — Combines endpoint specs, auth info, and enrichment into an OpenAPI 3.1 YAML document, a Restish configuration file, and optionally an auth helper script.
- **GraphQL** — Renders the TypeRegistry to an SDL schema string.

## LLM-first vs. mechanical-first

The two branches use different strategies:

The **REST pipeline is LLM-first** — the LLM identifies the base URL, groups URLs into patterns, and provides business context. Mechanical extraction fills in the schemas and parameters. This approach is more accurate for REST APIs where URL patterns are ambiguous and the same path can serve different purposes.

The **GraphQL pipeline is mechanical-first** — `__typename` injection and query parsing allow accurate type reconstruction without LLM involvement. The LLM only adds business descriptions. This works because GraphQL's type system is explicit enough to reconstruct mechanically.
