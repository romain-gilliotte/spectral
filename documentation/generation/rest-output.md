# REST output

The `openapi analyze` command produces an OpenAPI 3.1 YAML specification from captured REST traffic.

## Prerequisites

- At least one capture for the app (see [Capture](../capture/web.md))
- An Anthropic API key (configured via `spectral config`)

## Generating a spec

```bash
spectral openapi analyze myapp -o myapp
```

This writes `myapp.yaml` containing the full OpenAPI 3.1 specification.

The `--skip-enrich` flag produces a spec with only mechanical data (schemas, parameters, status codes) without business descriptions — useful for faster iteration or when you only need the structural information. The `--debug` flag saves all LLM prompts and responses to disk.

## What you get

The output follows the OpenAPI 3.1.0 specification with:

| Section | Contents |
|---------|----------|
| `info` | API title, version, and description |
| `servers` | Detected base URL |
| `paths` | All endpoint patterns with operations, parameters, request bodies, and responses |
| `components.schemas` | Reusable request/response schemas |

Each operation includes an `operationId`, `summary`, `tags`, typed parameters, and response schemas with descriptions. The LLM adds business-facing descriptions (operation summaries, parameter meanings, schema field descriptions) that a purely mechanical tool cannot produce.

## Tips for better results

- **Capture more workflows** — the spec only contains endpoints you exercised during capture. Re-capture and re-run analysis to fill gaps.
- **Multiple samples help** — when the same endpoint is called multiple times with different parameters or responses, schema inference produces more accurate results (optional fields, type unions).

## How it works

The pipeline uses an **LLM-first strategy** for structural decisions, with mechanical extraction for details.

**Base URL detection** — the LLM examines all unique URLs to identify the business API origin, filtering out CDN, analytics, and tracker domains.

**Endpoint grouping** — the LLM groups URLs into endpoint patterns with `{param}` syntax, identifying which path segments are variable (IDs, UUIDs, hashes).

**Mechanical extraction** — for each endpoint group, the pipeline infers request/response schemas from observed JSON bodies, detects path/query parameters, headers, and status codes. Schema inference merges multiple responses: union of keys, type inference, nullability tracking, format detection (dates, emails, UUIDs, URIs).

**LLM enrichment** — parallel LLM calls add business descriptions to each endpoint. Failures are isolated per endpoint.
