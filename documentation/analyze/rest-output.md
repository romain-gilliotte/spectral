# REST output

When REST traces are found in the capture bundle, the analyze command produces an OpenAPI 3.1 YAML specification.

## What the LLM infers

The LLM adds business semantics that a purely mechanical tool cannot produce:

| Field | Where it appears | Example |
|-------|-----------------|---------|
| Operation `summary` | Each path operation | "Retrieve monthly electricity consumption for the authenticated user" |
| Operation `description` | Each path operation | Detailed explanation of what the endpoint does, when it's called, and what to expect |
| Parameter `description` | Path and query parameters | "The billing period identifier in YYYY-MM format" |
| Schema property `description` | Request/response schemas | "Total energy consumed in kilowatt-hours" |
| Response `description` | Each status code | "Returns consumption data grouped by month with cost breakdown" |

## What is mechanical

Everything else comes directly from the captured traces without LLM involvement:

- Endpoint URL patterns and HTTP methods
- Request and response schemas (inferred from observed JSON bodies)
- Path parameters (identified by the LLM during grouping, but typed mechanically)
- Query parameters with types and observed values
- Request headers
- Response status codes
- Security schemes (detected from Authorization headers, API keys, cookies)
- Format annotations on string fields (dates, emails, UUIDs, URIs)

## Schema inference

Given multiple responses for the same endpoint, the pipeline builds a merged schema:

- Union of all keys seen across samples
- Type inference from observed values (string, number, integer, boolean, array, object)
- Fields marked as optional if not present in all responses
- Format detection: ISO 8601 dates, email addresses, UUIDs, URIs
- Nested objects and arrays are inferred recursively

When the `--skip-enrich` flag is used, the spec contains only mechanical data — schemas, parameters, status codes — without business descriptions.

## OpenAPI structure

The output follows the OpenAPI 3.1.0 specification. Key sections:

| Section | Contents |
|---------|----------|
| `info` | API title and version |
| `servers` | Detected base URL |
| `paths` | All endpoint patterns with operations |
| `components.securitySchemes` | Detected auth mechanisms (Bearer, API key, Cookie, OAuth2) |
| `security` | Global security requirement applied to all operations |

Each operation includes `summary`, `description`, `parameters`, `requestBody` (when applicable), and `responses` with JSON schemas.

## Companion files

In addition to the YAML spec, the analyze command produces:

- **Restish config** (`<name>.restish.json`) — A configuration entry that registers the API with Restish, including the base URL and auth setup. See [Calling the API](../getting-started/calling-the-api.md).
- **Auth helper** (`<name>-auth.py`) — When the LLM detects a reproducible auth flow, it generates a standalone Python script that handles login, token caching, and refresh. See [Auth detection](auth-detection.md).
