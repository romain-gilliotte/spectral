# First analysis

This guide turns a capture bundle into MCP tools or an API specification.

## Run the analysis

The primary command is `mcp analyze`, which generates MCP tool definitions from all captures for an app:

```bash
spectral mcp analyze myapp
```

To generate formal API specs instead, use `openapi analyze` (REST) or `graphql analyze` (GraphQL) with an output base name:

```bash
spectral openapi analyze myapp -o myapp-api
spectral graphql analyze myapp -o myapp-api
```

All commands load all captures for the app, merge them into a single bundle, and produce the appropriate output.

## What happens during analysis

The pipeline runs several steps, printing progress along the way:

1. **Load** — Loads and merges all captures for the app, reports trace, WebSocket, and context counts
2. **Extract pairs** — Collects all observed (method, URL) pairs from the traces
3. **Detect base URL** — The LLM identifies the business API origin, filtering out CDN, analytics, and tracker domains
4. **Filter** — Keeps only the traces that match the detected base URL
5. **Protocol split** — Separates REST and GraphQL traces
6. **Extraction** — Builds endpoint patterns (REST) or reconstructs types (GraphQL) from the raw traces
6. **Enrichment** — Parallel LLM calls add business semantics: operation summaries, parameter descriptions, response explanations
7. **Assembly** — Combines everything into the final output files

Authentication analysis is a separate step, run via `spectral auth analyze`. See [Auth detection](../analyze/auth-detection.md) for details.

## Output files

Each analyze command produces output specific to its protocol:

| Command | Output | Contents |
|---------|--------|----------|
| `mcp analyze` | `tools/*.json` in managed storage | MCP tool definitions for any HTTP/JSON API |
| `openapi analyze` | `<name>.yaml` | OpenAPI 3.1 specification (REST only) |
| `graphql analyze` | `<name>.graphql` | SDL schema with type descriptions (GraphQL only) |

## Options

Skip the LLM enrichment step to get a faster but less detailed spec:

```bash
spectral openapi analyze myapp -o myapp-api --skip-enrich
```

Use a different model:

```bash
spectral openapi analyze myapp -o myapp-api --model claude-sonnet-4-5-20250929
```

Save all LLM prompts and responses for inspection:

```bash
spectral openapi analyze myapp -o myapp-api --debug
```

See [Debug mode](../analyze/debug-mode.md) for details on reading the debug output.

## Next steps

- [Calling the API](calling-the-api.md) — use MCP tools or curl to make API calls
- [REST output](../analyze/rest-output.md) — understand the OpenAPI spec in detail
- [GraphQL output](../analyze/graphql-output.md) — understand the SDL schema in detail
