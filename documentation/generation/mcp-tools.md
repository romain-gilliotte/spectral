# MCP tools

MCP tools are the primary output of Spectral. They let AI agents call any discovered API directly — no browser automation, no manual integration code, no protocol-specific knowledge required.

## Prerequisites

- At least one capture for the app (see [Capture](../capture/web.md))
- An Anthropic API key (configured via `spectral config`)

## Generating tools

Run `mcp analyze` with the app name:

```bash
spectral mcp analyze myapp
```

This produces one tool per business capability discovered in the captures. Tools are stored in managed storage at `~/.local/share/spectral/apps/<app>/tools/`.

If the app requires authentication, set it up before using the tools:

```bash
spectral auth analyze myapp
spectral auth login myapp
```

The `--skip-enrich` flag skips business description generation for faster iteration. The `--debug` flag saves all LLM prompts and responses to disk.

## Connecting the MCP server

Register the server with your MCP client:

```bash
spectral mcp install
```

This auto-detects Claude Desktop and Claude Code and registers the server with each. Use `--target claude-desktop` or `--target claude-code` to install to a specific client only.

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

## Authentication

For tools that require authentication, the server automatically manages tokens:

- If a valid (non-expired) token exists in managed storage, its headers are injected into the request and body params are merged into the request body.
- If the token has expired but a refresh token is available, the server auto-refreshes before making the request.
- If no valid token is available, the server returns an error instructing the user to run `spectral auth login`.

Body params support APIs that pass credentials in the request body (Firebase auth, POST-based APIs) instead of HTTP headers. Both injection mechanisms are transparent — AI agents never need to handle authentication themselves.

## Re-running analysis

You can re-run `mcp analyze` at any time. New captures are merged with previous ones, and tool definitions are overwritten. This lets you iteratively expand coverage by capturing more workflows and re-analyzing.

## How it works

Each tool maps a business operation (like "search parking areas" or "get account balance") to an HTTP request template. Tools are protocol-agnostic: the same format works for REST, GraphQL, REST.li, custom RPC, or any other protocol over HTTP.

The `mcp analyze` pipeline processes each trace greedily:

1. All captures are loaded and merged into a single bundle.
2. The LLM identifies the business API origin, filtering out CDN, analytics, and tracker domains.
3. For each trace, a lightweight LLM call classifies it as a useful business capability or not (static assets, config endpoints, health checks are skipped).
4. For useful traces, a full LLM call builds the tool definition — HTTP method, path pattern, headers, parameters, request body template — using investigation tools (base64/URL/JWT decoding, trace inspection, schema inference).
5. Once a trace is claimed by a tool, it is removed from the working set.

When a tool is called at runtime, the server validates arguments against the tool's JSON Schema (with type coercion), resolves parameter placeholders in the request template, injects auth headers and body params if needed, and makes the HTTP request.
