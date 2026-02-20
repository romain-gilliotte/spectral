# GraphQL output

When GraphQL traces are found in the capture bundle, the analyze command produces an SDL (Schema Definition Language) schema.

## Type reconstruction

The pipeline reconstructs the GraphQL schema mechanically from captured queries and responses. The accuracy depends on whether `__typename` injection was enabled during capture.

### With `__typename` injection

When the Chrome extension injects `__typename` into queries, responses carry explicit type names for every object. The extraction step walks the parsed query's field tree alongside the response data and:

- Creates object types with their exact names from `__typename` values
- Tracks field nullability by observing null vs. non-null values across multiple responses
- Detects list fields from array values
- Infers scalar types from leaf values (String, Int, Float, Boolean, ID)
- Discovers enum types when a field has a small set of distinct string values

### Without `__typename`

For persisted queries (APQ hashes) and named operations where the extension cannot inject `__typename` or parse the query text, the pipeline can only infer types from response shapes. In this case:

- Type names are generated from the field path (less readable)
- Field-level nullability is less precise
- The schema is still usable but less accurate

## What the LLM adds

The LLM enrichment step makes parallel calls, one per type, and adds:

| Field | Where it appears | Example |
|-------|-----------------|---------|
| Type description | Before each `type` definition | "Represents a user's monthly electricity consumption with cost breakdown" |
| Field description | Before each field | "Total energy consumed during the billing period, in kilowatt-hours" |

The LLM sees each type's fields with their inferred types and a sample of observed values, giving it enough context to write meaningful descriptions.

## SDL structure

The output is a standard GraphQL SDL file with:

- **Object types** — reconstructed from response data, with field types and descriptions
- **Input types** — reconstructed from query variables
- **Enum types** — inferred from fields with small distinct value sets
- **Root fields** — `Query` and `Mutation` types listing the observed operations

## GraphQL request patterns

The pipeline recognizes three shapes of GraphQL requests:

| Pattern | Query text available | `__typename` injectable | Example clients |
|---------|---------------------|------------------------|-----------------|
| Normal query | Yes | Yes | Most GraphQL clients |
| Persisted query (APQ hash) | Only if APQ rejection forces fallback | Depends on fallback | Apollo clients |
| Named operation | No (name only) | No | Reddit |

For the best results, enable both `__typename` injection and persisted query blocking in the Chrome extension. See [Chrome extension](../capture/chrome-extension.md) for details on these toggles.

## Limitations

The reconstructed schema only contains types and fields that were observed during capture. If the application has endpoints you did not exercise, those types and fields will be missing. Run the capture again with broader coverage to fill in gaps.

Union types and interfaces are not reconstructed — the pipeline creates concrete object types for each `__typename` value it observes.
