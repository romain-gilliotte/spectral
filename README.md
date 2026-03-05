<p align="center">
  <img src="assets/banner.png" alt="Spectral" width="600">
</p>

Turn any app into an API that Claude can use. Browse normally, Spectral figures out the API, then AI agents call it directly.

Want Claude to pay for your parking, pull numbers from your accounting software, or search listings on your city's classifieds site — without brittle browser automation? Most apps sit on undocumented APIs that work perfectly well. Spectral captures the traffic, has an LLM figure out what each call means, and turns it into tools that Claude can call.

MCP tools work with any HTTP/JSON API regardless of protocol. Spectral can also generate formal API specs — OpenAPI 3.1 for REST APIs, SDL schemas for GraphQL — for human consumption and code generation.

**[Documentation](https://romain-gilliotte.github.io/spectral/)**

## How it works

1. **Capture** — Chrome extension (web) or MITM proxy records traffic + UI actions while you browse
2. **Analyze** — LLM correlates UI actions with API calls, infers endpoint patterns, auth flow, and business meaning
3. **Use** — Start the MCP server. Claude calls the API directly, with auth handled automatically

## Quick start

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), [Anthropic API key](https://console.anthropic.com/).

```bash
git clone https://github.com/romain-gilliotte/spectral.git && cd spectral
uv sync
```

Set up the Chrome extension and capture traffic:

```bash
# Load extension/ as unpacked in chrome://extensions, then connect it:
uv run spectral extension install --extension-id <id-from-chrome-extensions>

# Chrome extension: Start Capture → browse → Stop Capture → Send to Spectral
# Or use the MITM proxy (stores directly):
uv run spectral capture proxy -a myapp
```

Analyze captures, set up auth, and start the MCP server:

```bash
uv run spectral mcp analyze myapp                      # → MCP tool definitions
uv run spectral auth analyze myapp                     # → auth script (acquire/refresh tokens)
uv run spectral auth login myapp                       # interactive login
uv run spectral mcp stdio                              # start MCP server for AI agents
```

Or generate API specs (REST/GraphQL only):

```bash
uv run spectral openapi analyze myapp -o myapp-api    # → myapp-api.yaml (OpenAPI 3.1)
uv run spectral graphql analyze myapp -o myapp-api     # → myapp-api.graphql (SDL schema)
```

See the [getting started guide](https://romain-gilliotte.github.io/spectral/getting-started/installation/) for detailed setup, or the [CLI reference](https://romain-gilliotte.github.io/spectral/reference/cli/) for all commands.

## Capture methods

| Method                                                                                            | Best for                | UI context                             | Needs certification installation |
| ------------------------------------------------------------------------------------------------- | ----------------------- | -------------------------------------- | -------------------------------- |
| [Chrome extension](https://romain-gilliotte.github.io/spectral/capture/chrome-extension/)         | Web apps                | Yes — clicks, navigation, page content | No                               |
| [MITM proxy](https://romain-gilliotte.github.io/spectral/capture/mitm-proxy/)                     | CLI tools, desktop apps | No                                     | Yes — [setup guide](https://romain-gilliotte.github.io/spectral/capture/certificate-setup/) |
| [Android APK patching + MITM proxy](https://romain-gilliotte.github.io/spectral/capture/android/) | Mobile apps             | No                                     | Yes — [setup guide](https://romain-gilliotte.github.io/spectral/capture/certificate-setup/) |

## License

[MIT](LICENSE)
