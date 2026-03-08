---
hide:
  - toc
title: Spectral
---

# Spectral { .hidden-title }

![Spectral banner](assets/banner-dark.png){ .banner-img .only-dark }
![Spectral banner](assets/banner-light.png){ .banner-img .only-light }

Browse any website or mobile app normally. Spectral observes what you do, figures out the meaning behind each API call, and builds MCP tools that let AI agents use the same app.

![Spectral demo](assets/demo.gif)

## Why Spectral

Most apps — web, mobile, desktop — sit on top of undocumented HTTP APIs that work perfectly well. Without tooling, your only option for AI agents is browser automation: slow, fragile, and breaks on every UI change. Spectral takes a different approach. It captures the traffic while you browse, uses an LLM to understand what each call does, and generates MCP tools that any AI agent can call directly.

The key innovation is the correlation of UI actions with network traffic. Instead of just recording technical shapes, Spectral understands _why_ each API call exists — what business operation it represents, what the parameters mean, and how authentication works.

- **Works everywhere.** Websites, mobile apps (Android), desktop apps, CLI tools — if it speaks HTTPS, Spectral can capture it. The Chrome extension handles web apps; the MITM proxy handles everything else.

- **Understands what you do, not just what the network sends.** Spectral correlates your clicks and navigation with API calls to figure out the business meaning of each endpoint. The result is tools with meaningful names, descriptions, and parameters — not just raw HTTP shapes.

- **Tools that fix themselves.** When a generated tool fails at runtime, the MCP server feeds the error back to an LLM and patches the tool automatically. No manual debugging needed.

- **LLM at build time, not at runtime.** The LLM is only used during analysis and self-repair. Once your tools work, every call is a direct HTTP request — fast, cheap, and deterministic.

- **Faster than browser automation.** No headless browser, no fragile selectors, no waiting for pages to render. Spectral tools call the API directly, which is orders of magnitude faster and more reliable than controlling a browser with an agent.

- **Also generates API specs.** Beyond MCP tools, Spectral can produce OpenAPI 3.1 specs from REST traffic and GraphQL SDL schemas from GraphQL traces — useful for documentation, code generation, or feeding other tools. See [OpenAPI 3.0](generation/rest-output.md) and [GraphQL SDL](generation/graphql-output.md).

## How it works

Spectral is a four-stage pipeline:

1. **Capture** — A Chrome extension (web) or MITM proxy records network traffic and UI actions while you use the app normally. Multiple sessions can be accumulated for the same app to improve coverage.

2. **Analyze** — The CLI loads all captures for an app, merges them, then correlates what you clicked with what the app sent over the network. An LLM identifies useful business capabilities and builds a tool for each one.

3. **Authenticate** — The CLI detects the app's auth flow and generates a login script. Run it once to obtain a session; the MCP server refreshes it automatically.

4. **Use** — Start the MCP server. AI agents call the API directly. No browser, no selectors, no rendering.

## What you get

| Output               | Description                                                                                                                                                                                   |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **MCP tools**        | The primary output. Tool definitions for any HTTP/JSON API — AI agents call them directly via the MCP server. Works with REST, GraphQL, REST.li, custom RPC, or any other protocol over HTTP. |
| **Auth script**      | Token acquisition and refresh logic, generated from observed login flows. The MCP server uses it to inject auth headers and auto-refresh expired tokens.                                      |
| **OpenAPI 3.1 YAML** | Also available for REST APIs: endpoint patterns, request/response schemas, and business descriptions. Useful for documentation and code generation.                                           |
| **SDL schema**       | Also available for GraphQL APIs: reconstructed types with field descriptions, nullability, and list cardinality.                                                                              |

All formats include LLM-inferred business semantics that a purely mechanical tool could not produce: operation summaries, parameter descriptions, and authentication flow documentation.

## Next steps

[Getting started](getting-started.md) — install Spectral, capture traffic, and generate your first MCP tools in five minutes.
