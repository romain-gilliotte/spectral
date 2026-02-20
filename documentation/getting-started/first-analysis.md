# First analysis

This guide turns a capture bundle into an API specification.

## Run the analysis

Pass your capture bundle to the `analyze` command with an output base name:

```bash
uv run spectral analyze capture_20260213.zip -o myapp-api
```

The pipeline auto-detects whether the captured traffic is REST, GraphQL, or both, and produces the appropriate output files.

## What happens during analysis

The pipeline runs several steps, printing progress along the way:

1. **Load** — Reads the bundle and reports trace, WebSocket, and context counts
2. **Detect base URL** — The LLM identifies the business API origin, filtering out CDN, analytics, and tracker domains
3. **Filter** — Keeps only the traces that match the detected base URL
4. **Protocol split** — Separates REST and GraphQL traces
5. **Extraction** — Builds endpoint patterns (REST) or reconstructs types (GraphQL) from the raw traces
6. **Enrichment** — Parallel LLM calls add business semantics: operation summaries, parameter descriptions, response explanations
7. **Auth analysis** — A separate LLM call examines all traces (including those outside the base URL) to detect the authentication mechanism
8. **Assembly** — Combines everything into the final output files

## Output files

Depending on the protocols detected, the command produces some or all of these files:

| File | When produced | Contents |
|------|---------------|----------|
| `myapp-api.yaml` | REST traces found | OpenAPI 3.1 specification |
| `myapp-api.graphql` | GraphQL traces found | SDL schema with type descriptions |
| `myapp-api.restish.json` | REST traces found | Restish configuration entry for this API |
| `myapp-api-auth.py` | Auth detected and analyzable | Standalone Python auth helper script |

## Options

Skip the LLM enrichment step to get a faster but less detailed spec:

```bash
uv run spectral analyze capture.zip -o myapp-api --skip-enrich
```

Use a different model:

```bash
uv run spectral analyze capture.zip -o myapp-api --model claude-sonnet-4-5-20250929
```

Save all LLM prompts and responses for inspection:

```bash
uv run spectral analyze capture.zip -o myapp-api --debug
```

See [Debug mode](../analyze/debug-mode.md) for details on reading the debug output.

## Next steps

- [Calling the API](calling-the-api.md) — use the generated spec and Restish config to make API calls
- [REST output](../analyze/rest-output.md) — understand the OpenAPI spec in detail
- [GraphQL output](../analyze/graphql-output.md) — understand the SDL schema in detail
