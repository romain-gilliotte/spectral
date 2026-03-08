# MCP tools

MCP tools are the primary output of Spectral. They let AI agents call any discovered API directly — no browser automation, no manual integration code, no protocol-specific knowledge required.

## What MCP tools are

Each tool is a self-contained definition that maps a business operation (like "search parking areas" or "get account balance") to an HTTP request. The definition includes a name, a description, typed parameters with a JSON Schema, and a request template that the MCP server fills in at runtime. Tools are protocol-agnostic: the same format works for REST, GraphQL, REST.li, custom RPC, or any other protocol over HTTP.

## How `mcp analyze` works

The `mcp analyze` command takes all captures for an app and produces tool definitions. It runs a greedy, per-trace pipeline:

1. **Load and merge** — All captures for the app are loaded and merged into a single bundle, with trace IDs prefixed by capture index to avoid collisions.

2. **Detect base URL** — The LLM examines all observed URLs to identify the business API origin, filtering out CDN, analytics, and tracker domains. The result is cached in `app.json` for subsequent runs.

3. **Filter** — Only traces matching the detected base URL are kept.

4. **Build context** — A shared context block is constructed containing the base URL and a chronological session timeline (UI actions interleaved with API calls). This context is reused across all subsequent LLM calls for prompt caching efficiency.

5. **Identify and build** — For each unclaimed trace, the pipeline asks two questions:
    - *Is this a useful business capability?* A lightweight LLM call classifies the trace. Static assets, configuration endpoints, health checks, and auth endpoints are skipped.
    - *What tool should this become?* If useful, a full LLM call builds the tool definition using investigation tools (base64/URL/JWT decoding, trace inspection, schema inference). The LLM determines the HTTP method, path pattern with parameter placeholders, headers, query parameters, request body template, and which traces this tool consumes.

6. **Store** — Tool definitions are written to managed storage as individual JSON files under `tools/` in the app directory.

The pipeline processes traces greedily: once a trace is claimed by a tool, it is removed from the working set. This continues until all traces are processed or skipped.

## Tool definition format

Each tool is stored as a JSON file in managed storage at `~/.local/share/spectral/apps/<app>/tools/<tool_name>.json`.

A tool definition contains:

| Field | Description |
|-------|-------------|
| `name` | Snake-case identifier for the tool |
| `description` | Business-facing description explaining when to use this tool |
| `parameters` | JSON Schema object defining typed input parameters |
| `request` | HTTP request template: method, path (with `{param}` placeholders), headers, query, body (with parameter references), and content type |
| `requires_auth` | Whether the MCP server should inject auth headers when executing this tool |

The request template uses two kinds of parameter references: `{param}` placeholders in the URL path, and `{"$param": "name"}` markers in query parameters and request body fields. Fixed values (constants observed across all traces) are stored as literals. When a referenced parameter is not provided at runtime, the key is omitted from the request.

## The MCP server

The `mcp stdio` command starts an MCP server that exposes all tools from managed storage over the stdio transport.

When a tool is called, the server:

1. Validates the arguments against the tool's JSON Schema, with type coercion (strings to numbers/booleans) and default value application.
2. Resolves the request template — substitutes parameter references in the path, query, and body.
3. Injects auth headers if the tool requires authentication (see below).
4. Makes the HTTP request and returns the response to the agent.

The server is stateless: each tool call is independent, with no conversation or session state.

### Configuring your MCP client

The easiest way to register the MCP server is:

```bash
spectral mcp install
```

This auto-detects Claude Desktop and Claude Code, and registers the server with each. Use `--target claude-desktop` or `--target claude-code` to install to a specific client only. The command resolves the absolute path to the `spectral` executable so the server works regardless of shell PATH.

For other MCP clients, add a stdio server entry with the command `spectral mcp stdio`. For example, in a JSON config file:

```json
{
  "mcpServers": {
    "spectral": {
      "command": "spectral",
      "args": ["mcp", "stdio"]
    }
  }
}
```

### Authentication injection

For tools that require authentication, the server automatically manages tokens:

- If a valid (non-expired) token exists in managed storage, its headers are injected into the request.
- If the token has expired but a refresh token is available, the server auto-refreshes using the generated auth script before making the request.
- If no valid token is available, the server returns an error instructing the user to run `spectral auth login`.

This means AI agents never need to handle authentication themselves — the server takes care of it transparently.

## Protocol agnosticism

Unlike the `openapi analyze` and `graphql analyze` commands, which produce protocol-specific output (OpenAPI specs or SDL schemas), MCP tool generation treats all protocols uniformly as HTTP request/response pairs. The LLM identifies business capabilities regardless of whether the underlying API is REST, GraphQL with persisted queries, a single-endpoint RPC service, or a custom protocol. This makes MCP tools the most versatile output format — they work with any HTTP/JSON API without requiring protocol-specific handling.
