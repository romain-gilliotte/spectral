# GraphQL output

When GraphQL traces are found in the capture bundle, the analyze command produces an SDL (Schema Definition Language) schema.

## Type reconstruction

The pipeline reconstructs the GraphQL schema mechanically from captured queries and responses. The accuracy depends on whether `__typename` injection was enabled during capture.

### With `__typename` injection

When the Chrome extension injects `__typename` into queries, responses carry explicit type names for every object. The extraction step walks the parsed query's field tree alongside the response data and:

- Creates object types with their exact names from `__typename` values
- Tracks field nullability by observing null vs. non-null values across multiple responses
- Detects list fields from array values
- Infers scalar types from leaf values (String, Int, Float, Boolean)
- Discovers enum types from query variable declarations whose type annotation is not a built-in scalar, and from bare enum literals in query arguments

### Without `__typename`

Traces that have no query text (persisted queries sent as a hash only, named operations without the full query) are skipped entirely — the parser cannot reconstruct a field tree without the query string.

When the query text is available but `__typename` is absent from responses, the pipeline walks the query field tree but skips object fields whose type cannot be determined. A type name is resolved only from inline fragment type conditions (`... on SomeType`). Without either `__typename` or a type condition, the object subtree is not recursed into and no type is created in the registry. Scalar fields and fields with type conditions from inline fragments are still extracted normally.

For the best results, ensure `__typename` injection is enabled during capture. See [Chrome extension](../capture/chrome-extension.md) for details.

## What the LLM adds

The LLM enrichment step makes parallel calls, one per type and one per enum, and adds:

| Field | Where it appears | Example |
|-------|-----------------|---------|
| Type description | Before each `type` or `enum` definition | "Represents a user's monthly electricity consumption with cost breakdown" |
| Field description | Before each field | "Total energy consumed during the billing period, in kilowatt-hours" |

The LLM sees each type's fields with their inferred types and a sample of observed values, giving it enough context to write meaningful descriptions.

## SDL structure

The output is a standard GraphQL SDL file with:

- **Object types** — reconstructed from response data, with field types and descriptions
- **Input types** — reconstructed from query variables
- **Enum types** — inferred from fields with small distinct value sets
- **Root fields** — `Query`, `Mutation`, and `Subscription` types listing the observed operations

## GraphQL request patterns

The pipeline recognizes three shapes of GraphQL requests:

| Pattern | Query text available | `__typename` injectable | Example clients |
|---------|---------------------|------------------------|-----------------|
| Normal query | Yes | Yes | Most GraphQL clients |
| Persisted query (APQ hash) | Only if APQ rejection forces fallback | Depends on fallback | Apollo clients |
| Named operation | No (name only) | No | Some proprietary clients |

For the best results, enable both `__typename` injection and persisted query blocking in the Chrome extension. See [Chrome extension](../capture/chrome-extension.md) for details on these toggles.

## Limitations

The reconstructed schema only contains types and fields that were observed during capture. If the application has endpoints you did not exercise, those types and fields will be missing. Run the capture again with broader coverage to fill in gaps.

Union types and interfaces are not reconstructed — the pipeline creates concrete object types for each `__typename` value it observes.
