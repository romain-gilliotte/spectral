# GraphQL output

The `graphql analyze` command produces an SDL (Schema Definition Language) schema from captured GraphQL traffic.

## Prerequisites

- At least one capture for the app (see [Capture](../capture/web.md))
- An Anthropic API key (set via `ANTHROPIC_API_KEY` or `config.json` — run `spectral config`)
- For best results, enable `__typename` injection in the Chrome extension during capture

## Generating a schema

```bash
spectral graphql analyze myapp -o myapp
```

This writes `myapp.graphql` containing the reconstructed SDL schema.

The `--skip-enrich` flag produces a schema without business descriptions — useful for faster iteration. The `--debug` flag saves all LLM prompts and responses to disk.

## What you get

The output is a standard GraphQL SDL file with:

- **Object types** — reconstructed from response data, with field types and descriptions
- **Input types** — reconstructed from query variables
- **Enum types** — inferred from fields with small distinct value sets
- **Root fields** — `Query`, `Mutation`, and `Subscription` types listing the observed operations

The LLM adds business-facing descriptions to each type and field based on their observed values and context.

## Tips for better results

- **Enable `__typename` injection** — this is the single most important setting. With `__typename`, every object in the response carries its exact type name, producing accurate type definitions. Without it, many object types cannot be reconstructed. See [Web capture](../capture/web.md) for details.
- **Block persisted queries** — some GraphQL clients send a hash instead of the full query text. Blocking persisted queries forces the client to send the full query, which the pipeline needs to reconstruct the field tree. See [Web capture](../capture/web.md).
- **Capture more operations** — the schema only contains types and fields observed during capture. Exercise more workflows to fill gaps.

## Limitations

- The schema only contains types and fields that were observed during capture.
- Union types and interfaces are not reconstructed — the pipeline creates concrete object types for each `__typename` value.
- Traces without query text (persisted queries sent as a hash only) are skipped entirely.

## How it works

The pipeline uses a **mechanical-first strategy** — the GraphQL type system is explicit enough to reconstruct accurately without LLM involvement. The LLM only adds business descriptions.

**Type extraction** — all GraphQL queries are parsed using `graphql-core`. The parser walks the field tree alongside the JSON response data, reconstructing object types, input types, enums, and scalars. With `__typename` present, types get their exact names. Without it, types are inferred from response shapes (less precise — only inline fragment type conditions provide a type name).

**LLM enrichment** — parallel LLM calls add descriptions to each type and its fields. Each call receives the type's fields with their observed values. Failures are isolated per type.
