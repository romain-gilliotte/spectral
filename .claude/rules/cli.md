---
paths:
  - "cli/**/*"
  - "tests/**/*"
---

# CLI — Analysis Pipeline and Architecture

## Capture bundle format

The custom ZIP format produced by the Chrome Extension and consumed by the CLI. Chosen over HAR for binary support, WebSocket support, UI context, and stable trace IDs.

### Bundle structure

```
capture_<timestamp>.zip
├── manifest.json              # Session metadata (format_version, capture_id, app, browser, stats)
├── traces/
│   ├── t_NNNN.json            # Trace metadata (method, url, headers, status, timing, context_refs)
│   ├── t_NNNN_request.bin     # Raw request body (binary-safe)
│   └── t_NNNN_response.bin    # Raw response body (binary-safe)
├── ws/
│   ├── ws_NNNN.json           # WS connection metadata (url, protocols, handshake_trace_ref)
│   ├── ws_NNNN_mNNN.json      # Message metadata (direction, opcode, connection_ref)
│   └── ws_NNNN_mNNN.bin       # Message payload
├── contexts/
│   └── c_NNNN.json            # UI context (action, element, page content, viewport)
└── timeline.json              # Ordered events with cross-references (type + ref)
```

Key design decisions:
- **`id`** is a stable string (`t_NNNN`) — contexts, timeline, and analysis can reference it
- **`body_file`** points to the companion `.bin` file — binary-safe, no base64
- **`body_encoding`** is null for raw binary; set to `"base64"` only if originally base64 in the protocol
- **`context_refs`** links to UI context(s) active when this trace was captured
- **Headers are arrays, not objects** — HTTP allows duplicate header names

UI context `page.content` fields: `headings` (h1-h3, up to 10), `navigation` (nav links, up to 15), `main_text` (max 500 chars), `forms` (up to 5), `tables` (headers, up to 5), `alerts` (up to 5).

Captured UI actions: `click`, `input` (field identity only, no value), `submit`, `navigate`.

The flat timeline makes correlation trivial: scan forward from a context event within a time window.

## Analysis output

- **REST** → OpenAPI 3.1 YAML, enriched with LLM-inferred `summary`/`description` and `x-` extensions
- **GraphQL** → SDL schema with type/field descriptions inferred by the LLM
- **MCP** → `ToolDefinition` JSON files in managed storage
- **Auth** → `auth_acquire.py` script with `acquire_token()` and optionally `refresh_token()`

A single capture can contain both REST and GraphQL traces; the pipeline processes them in parallel.

## Analysis pipeline (Step-based architecture)

The `build_spec()` function in `pipeline.py` orchestrates a Step-based pipeline. Each step is a typed `Step[In, Out]` with `run()` method, optional validation, and retry for LLM steps.

**Common steps** (sequential):
1. **Extract pairs** — `MechanicalStep`: collect `(method, url)` pairs from all traces
2. **Detect base URL** — `LLMStep`: identify the business API origin (with investigation tools, call frequency hints)
3. **Filter traces** — `MechanicalStep`: keep only traces matching the base URL
4. **Split by protocol** — traces are separated into REST and GraphQL groups

**REST branch** (when REST traces are present):
1. **Group endpoints** — `LLMStep`: group URLs into endpoint patterns with `{param}` syntax
2. **Strip prefix** — `MechanicalStep`: remove base URL path prefix from patterns
3. **Mechanical extraction** — `MechanicalStep`: build `EndpointSpec[]` with schemas, params
4. **Detect auth & rate limit** — mechanical per-endpoint detection from trace headers
5. **Enrich endpoints** — `LLMStep`: N parallel per-endpoint LLM calls for business semantics (via `asyncio.gather`)
6. **Assembly** — `MechanicalStep`: combine all outputs into OpenAPI 3.1 dict

**GraphQL branch** (when GraphQL traces are present):
1. **Extraction** — `MechanicalStep`: parse queries via `graphql-core`, walk response data with `__typename` to reconstruct a `TypeRegistry`
2. **Enrich types** — `LLMStep`: N parallel per-type LLM calls for descriptions
3. **Assembly** — `MechanicalStep`: render `TypeRegistry` → SDL string

Both branches run in parallel via `asyncio.gather`.

**MCP pipeline** (`spectral mcp analyze`, separate from REST/GraphQL):
1. Common steps (extract pairs + detect base URL + filter traces)
2. Build shared context for prompt caching
3. Greedy per-trace loop (up to 200 iterations): Identify (lightweight LLM filter) → Build tool (full definition with investigation tools) → consume traces

**Auth pipeline** (`spectral auth analyze`, separate from other pipelines):
1. Common steps (extract pairs + detect base URL)
2. Build shared context for prompt caching
3. Generate auth script — `LLMStep` with `inspect_trace` tool, generates `acquire_token()` and `refresh_token()` functions
4. Wrapped with auth framework (`cli/helpers/auth_framework.py`) for token caching, credential prompts

### Step classes (`cli/commands/analyze/steps/base.py`)

| Class | Behavior |
|---|---|
| `Step[In, Out]` | Base: calls `_execute()` then `_validate_output()` |
| `MechanicalStep` | No retry — validation failure is a bug |
| `LLMStep` | Retries on `StepValidationError` (max_retries=1), appends errors to conversation |

### LLM steps

| Step | File | Tools | Validation |
|---|---|---|---|
| Detect base URL | `steps/detect_base_url.py` | decode_base64, decode_url, decode_jwt | Valid URL (scheme + host) |
| Group endpoints (REST) | `steps/rest/group_endpoints.py` | decode_base64, decode_url, decode_jwt | Coverage, pattern match, no duplicates |
| Enrich endpoints (REST) | `steps/rest/enrich.py` | none | Best-effort (no validation) |
| Enrich types (GraphQL) | `steps/graphql/enrich.py` | none | Best-effort (no validation) |
| Identify capability (MCP) | `steps/mcp/identify.py` | none | Structured response (useful, name, description) |
| Build tool (MCP) | `steps/mcp/build_tool.py` | inspect_trace, inspect_context, query_traces | Valid ToolDefinition |
| Generate auth script | `steps/generate_auth_script.py` | inspect_trace | Compiles, defines `acquire_token` |

All LLM steps use `_extract_json()` to robustly parse LLM JSON responses (handles markdown blocks, nested objects).

### Internal data flow

| Type | Location | Purpose |
|---|---|---|
| `MethodUrlPair` | `steps/types.py` | An observed (method, url) pair from a single trace |
| `AnalysisResult` | `steps/types.py` | Final output: optional `openapi` dict + optional `graphql_sdl` string |
| `EndpointGroup` | `steps/rest/types.py` | An LLM-identified REST endpoint group (method, pattern, urls) |
| `EndpointSpec` | `steps/rest/types.py` | Full REST endpoint with request/response schemas |
| `SpecComponents` | `steps/rest/types.py` | All pieces needed for the REST assembly step |
| `TypeRegistry` | `steps/graphql/types.py` | Accumulated GraphQL types, fields, enums from all traces |
| `GraphQLSchemaData` | `steps/graphql/types.py` | Final GraphQL schema with root fields + type registry |
| `ToolCandidate` | `steps/mcp/types.py` | A proposed MCP tool before full definition |
| `McpPipelineResult` | `steps/mcp/types.py` | Final MCP output: list of tools + base_url |
| `ToolDefinition` | `formats/mcp_tool.py` | Pydantic model: MCP tool with name, params, request template |
| `TokenState` | `formats/mcp_tool.py` | Pydantic model: persisted auth state (headers, refresh_token, expires) |

## Managed storage (`cli/helpers/storage.py`)

All CLI commands read from and write to a per-app directory tree under `~/.local/share/spectral/` (overridable with `SPECTRAL_HOME`). This is the central data layer — captures, analysis outputs, auth state, and MCP tools all live here.

```
apps/<name>/
├── app.json              # AppMeta: name, display_name, base_url, timestamps
├── auth_acquire.py       # Generated by `auth analyze` — acquire_token(), refresh_token()
├── token.json            # TokenState: current auth headers, refresh_token, expires_at
├── tools/
│   └── <tool_name>.json  # ToolDefinition: generated by `mcp analyze`
└── captures/
    └── <timestamp>_<source>_<id-prefix>/
        ├── manifest.json, traces/, ws/, contexts/, timeline.json
```

### Storage API

| Function | Purpose |
|---|---|
| `import_capture(app, zip_path)` | Import a ZIP bundle into flat-directory format |
| `store_capture(app, bundle)` | Write an in-memory bundle to storage |
| `list_apps()` / `list_captures(app)` | Enumerate apps and their captures |
| `load_app_bundle(app)` | Load + merge all captures for an app into one bundle |
| `write_token` / `load_token` / `delete_token` | Auth state persistence (TokenState) |
| `write_tools` / `load_tools` | MCP tool definitions (list of ToolDefinition) |
| `auth_script_path(app)` | Path to generated auth script |
| `app_dir(app)` / `ensure_app(app)` | App directory resolution and creation |

### How commands use storage

- **`capture proxy`** calls `store_capture` to write live-captured flows directly.
- **`openapi analyze` / `graphql analyze`** call `load_app_bundle` to get a merged bundle, then write output files (not in storage — written to `-o` path).
- **`mcp analyze`** calls `load_app_bundle`, runs the MCP pipeline, then `write_tools` to persist tool definitions.
- **`auth analyze`** generates `auth_acquire.py` in the app directory.
- **`auth set`** calls `write_token` to persist manually-provided headers/cookies.
- **`auth login`** executes the auth script and calls `write_token` with the result.
- **`mcp stdio`** calls `load_tools` + `load_token` for each app to build the tool registry.

### Bundle merging

`merge_bundles` in `cli/commands/capture/types.py` prefixes IDs with a 3-digit capture index to avoid collisions (e.g. `t_0001` from capture 2 becomes `t_002_0001`). A single-capture list is returned as-is without renaming.

### Flat-directory format

Storage uses unpacked flat directories (not ZIPs) for captures. The loader (`cli/commands/capture/loader.py`) provides both `load_bundle` (ZIP) and `load_bundle_dir` (flat directory), plus `write_bundle_dir` for writing. Same structure as the ZIP, just on disk.

## Key technical notes

### LLM-first analysis strategy (REST)
The REST pipeline is LLM-first (not mechanical-first with LLM enrichment):
1. The LLM identifies the business API base URL — filtering out CDN, analytics, trackers
2. The LLM groups URLs into endpoint patterns — more accurate than mechanical heuristics for complex APIs
3. For each group, mechanical extraction provides the raw data (schemas, params, headers)
4. N parallel per-endpoint LLM calls enrich each endpoint with focused business semantics
5. Per-step validation catches LLM mistakes (coverage, pattern mismatches) and retries once

Per-endpoint enrichment trades a single large prompt for N small focused prompts. Failures are isolated. All calls run concurrently via `asyncio.gather`.

### GraphQL analysis strategy
The GraphQL pipeline is mechanical-first with LLM enrichment:
1. The extension injects `__typename` into all GraphQL queries at capture time, so responses carry type information
2. The extraction step parses queries via `graphql-core` and walks the parsed field tree alongside the JSON response data to reconstruct a `TypeRegistry`
3. N parallel per-type LLM calls add descriptions to types and fields
4. The assembly step renders the `TypeRegistry` to SDL

For persisted/named queries where we cannot inject `__typename` or parse the query text, the pipeline can only infer types from response shapes (less precise).

### Path parameter inference
Path parameters are inferred by the LLM during URL grouping. The LLM sees all observed URLs and identifies variable segments to produce patterns like `/api/users/{user_id}/orders`. The mechanical `_pattern_to_regex()` helper converts these patterns to regexes for validation.

### Schema inference (mechanical)
Given multiple JSON response bodies for the same endpoint (`cli/commands/analyze/schemas.py`):
- Union of all keys seen across samples
- For each key: infer type from values (string, number, boolean, array, object)
- Mark keys as optional if not present in all responses
- Detect common formats: ISO dates, emails, UUIDs, URLs
- Annotated schemas add up to 5 `observed` values per property for LLM context

### GraphQL request patterns

Both the Python protocol detector (`_is_graphql_item` in `protocol.py`) and the extension's interception filter recognize three shapes:

| Pattern | Shape | Query text available |
|---|---|---|
| **Normal query** | `{"query": "query { ... }", ...}` | Yes |
| **Persisted query (hash)** | `{"extensions": {"persistedQuery": {...}}, ...}` | No (hash only) |
| **Named operation** | `{"operation": "FetchUsers", "variables": {...}}` | No (name only) |

The `operationName` key is also accepted in place of `operation`. Both require a `variables` dict to distinguish from arbitrary JSON.
