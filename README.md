<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/romain-gilliotte/spectral/main/assets/banner-wide-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/romain-gilliotte/spectral/main/assets/banner-wide-light.png">
    <img src="https://raw.githubusercontent.com/romain-gilliotte/spectral/main/assets/banner-wide-dark.png" alt="Spectral" width="600">
  </picture>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#why-spectral">Why Spectral</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="https://romain-gilliotte.github.io/spectral/"><strong>Documentation</strong></a>
</p>

Browse any website or mobile app normally. Spectral observes what you do, figures out the meaning behind each API call, and builds MCP tools that let AI agents use the same app.

<p align="center">
  <img src="https://raw.githubusercontent.com/romain-gilliotte/spectral/main/assets/demo.gif" width="750" alt="Spectral demo — analyze traffic, then Claude uses the API">
</p>

## Why Spectral

Most apps — web, mobile, desktop — sit on top of undocumented HTTP APIs. Spectral records the traffic while you browse, uses an LLM to understand what each call does, and generates MCP tools that any AI agent can call.

- **Works everywhere.** Websites, mobile apps (Android), desktop apps, CLI tools — if it speaks HTTPS, Spectral can capture it.

- **Understands what you do, not just what the network sends.** Spectral correlates your clicks and navigation with API calls to figure out the business meaning of each endpoint — not just its shape.

- **Tools that fix themselves.** When a generated tool fails at runtime, the MCP server feeds the error back to an LLM and patches the tool automatically.

- **LLM at build time, not at runtime.** The LLM is only used during analysis and self-repair. Once your tools work, every call is a direct HTTP request — fast, cheap, and deterministic.

- **Faster than browser automation.** No headless browser, no fragile selectors, no waiting for pages to render. Spectral tools call the API directly, which is orders of magnitude faster and more reliable than controlling a browser with an agent.

- **Also generates API specs.** Beyond MCP tools, Spectral can produce OpenAPI 3.1 specs from REST traffic and GraphQL SDL schemas from GraphQL traces — useful for documentation, code generation, or feeding other tools.

## Install

```bash
pip install spectral-mcp
```

or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install spectral-mcp
```

Alternatively, install from source with the one-liner:

```bash
curl -LsSf https://raw.githubusercontent.com/romain-gilliotte/spectral/main/install.sh | bash
```

You also need an [Anthropic API key](https://console.anthropic.com/) — Spectral will prompt for it on first analysis.

See the [documentation](https://romain-gilliotte.github.io/spectral/) for setup guides, capture instructions, and CLI reference.

## How it works

1. **Capture** — Chrome extension (web) or MITM proxy records traffic while you use the app
2. **Analyze** — An LLM correlates your actions with API calls, infers endpoint patterns, and business meaning
3. **Authenticate** — The CLI detects the auth flow and generates a login script. Run it once; the MCP server refreshes automatically
4. **Use** — Start the MCP server. AI agents call the API directly

## License

[MIT](LICENSE)
