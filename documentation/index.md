# Spectral

Reverse-engineer any app's private API. Browse normally, get a full spec — then use it to build AI agents and automations instead of brittle browser scripts.

Most apps sit on undocumented APIs that work perfectly well. But without a spec, people fall back to Playwright, Selenium, or Puppeteer: slow, fragile, breaks on every UI change, can't handle mobile. Spectral captures the traffic, has an LLM figure out what each call means, and gives you a spec you can actually use.

## How it works

Spectral is a two-stage pipeline:

1. **Capture** — A Chrome extension or MITM proxy records network traffic and UI actions while you browse the app normally. The output is a portable ZIP bundle containing every HTTP request/response, WebSocket message, and UI interaction.

2. **Analyze** — A CLI tool correlates what you clicked with what the app sent over the network, using an LLM to understand the business meaning of each API call. REST traces produce an OpenAPI 3.1 spec; GraphQL traces produce a typed SDL schema.

The key innovation is the correlation of UI actions with network traffic. Instead of just recording technical shapes, Spectral understands *why* each API call exists — what business operation it represents, what the parameters mean, how authentication works.

## What you get

| Protocol | Output | Contents |
|----------|--------|----------|
| REST | OpenAPI 3.1 YAML | Endpoint patterns, request/response schemas, business descriptions, auth flow |
| GraphQL | SDL schema | Reconstructed types with field descriptions, nullability, and list cardinality |

Both formats include LLM-inferred business semantics that a purely mechanical tool could not produce: operation summaries, parameter descriptions, and authentication flow documentation.

The analyze command also generates a Restish configuration file and, when auth is detected, a standalone Python auth helper script. Together these let you start calling the API immediately from the command line.

## Next steps

- [Installation](getting-started/installation.md) — set up Spectral on your machine
- [First capture](getting-started/first-capture.md) — record traffic from a web app
- [First analysis](getting-started/first-analysis.md) — turn a capture into an API spec
- [Calling the API](getting-started/calling-the-api.md) — use the generated spec to make API calls with Restish
