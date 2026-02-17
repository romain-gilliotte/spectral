# api-discover

Automatic API reverse-engineering for Android and the web.

Browse any app normally — api-discover captures network traffic alongside UI context (clicks, navigation, page content), then uses an LLM to correlate the two. The result is a semantically-rich API specification that describes not just the technical shape of each endpoint, but its business meaning: what it does, why a user triggers it, and how it fits into the application's workflows.

## Why

Most apps sit on top of private APIs that are perfectly usable — but undocumented. Today the common workaround is browser automation (Playwright, Selenium, Puppeteer): slow, flaky, breaks on every UI change, and can't handle mobile apps. Hitting the API directly is faster, more reliable, and works everywhere. You just need to know what the API looks like.

- **Automation** — turn any web or mobile app into a programmable API without writing brittle browser scripts
- **AI agents** — feed discovered specs to agent frameworks so they can interact with private APIs
- **Workflow platforms** — integrate private APIs into n8n, Make, or Zapier-like tools using the generated OpenAPI or MCP server
- **Documentation** — auto-generate human-readable docs for internal or undocumented APIs

## How it works

**Capture** — A Chrome extension (web) or MITM proxy (Android) records network traffic and UI actions while the user browses the app normally. No instrumentation, no code changes — just use the app.

**Analyze** — An LLM correlates UI actions with API calls, identifies endpoint patterns, infers business meaning, detects the authentication flow, and extracts domain context. The output is an enriched API spec that goes far beyond what mechanical tools can produce.

**Generate** — The spec feeds into generators that produce ready-to-use outputs: OpenAPI 3.1, MCP server scaffolds, Python clients with business-named methods, markdown docs, and cURL scripts.

## Quick start

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), an [Anthropic API key](https://console.anthropic.com/).

```bash
# Install
git clone https://github.com/eloims/api-discover.git
cd api-discover
uv sync

# Set your API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Analyze a capture bundle
uv run api-discover analyze capture.zip -o spec.json

# Generate outputs
uv run api-discover generate spec.json --type openapi -o openapi.yaml
uv run api-discover generate spec.json --type mcp-server -o mcp-server/
```

## Capture methods

### Web (Chrome Extension)

1. Open `chrome://extensions`, enable Developer Mode, click "Load unpacked" and select the `extension/` directory
2. Navigate to the target app and click the extension icon
3. Click **Start Capture**, then browse the app normally — every page navigation, button click, and form submission is recorded alongside the network traffic it triggers
4. Click **Stop Capture**, then **Export Bundle** to download a `.zip` capture bundle

### Android

The Android pipeline pulls an APK from a connected device, patches it to trust user-installed CA certificates (required for MITM), reinstalls it, and runs a proxy to capture traffic.

```bash
# 1. Find the package
uv run api-discover android list spotify

# 2. Pull the APK(s) from the device
uv run api-discover android pull com.spotify.music

# 3. Patch to trust user CA certs
uv run api-discover android patch com.spotify.music.apk

# 4. Install the patched APK
uv run api-discover android install com.spotify.music-patched.apk

# 5a. Discovery mode — find which domains the app talks to
uv run api-discover android capture

# 5b. Capture mode — intercept specific domains
uv run api-discover android capture -d "api\.spotify\.com" -o spotify.zip
```

## CLI reference

### Capture (Android)

| Command | Description |
|---|---|
| `android list [filter]` | List packages on connected device, optionally filtered by substring |
| `android pull <package> [-o path]` | Pull APK(s) from device (handles split APKs) |
| `android patch <apk> [-o path]` | Patch APK to trust user CA certificates for MITM |
| `android install <apk>` | Install APK or split APK directory to device |
| `android capture [-d domain...] [-p port] [-o bundle.zip]` | MITM proxy capture; without `-d`, runs in discovery mode |

### Analyze

```
api-discover analyze <bundle> -o spec.json [--model MODEL] [--debug] [--skip-enrich]
```

Analyze a capture bundle into an enriched API spec. Requires `ANTHROPIC_API_KEY`.

| Option | Default | Description |
|---|---|---|
| `--model` | `claude-sonnet-4-5-20250929` | LLM model to use |
| `--debug` | off | Save LLM prompts/responses to `debug/` |
| `--skip-enrich` | off | Skip business context enrichment |

### Generate

```
api-discover generate <spec> --type <type> -o <path>
```

Generate outputs from an enriched API spec.

| Type | Output |
|---|---|
| `openapi` | OpenAPI 3.1 YAML |
| `mcp-server` | FastMCP server scaffold (directory) |
| `python-client` | Python SDK with typed, business-named methods |
| `markdown-docs` | Human-readable documentation (directory) |
| `curl-scripts` | Ready-to-use cURL examples (directory) |

### Pipeline

```
api-discover pipeline <bundle> --types openapi,mcp-server -o output/
```

Run analyze + generate in one shot. Accepts the same `--model`, `--debug`, and `--skip-enrich` options as `analyze`.

### Utilities

| Command | Description |
|---|---|
| `inspect <bundle> [--trace t_NNNN]` | Inspect a capture bundle (summary or single trace detail) |
| `call <spec> --list` | List discovered endpoints |
| `call <spec> <endpoint> [key=value...]` | Call an endpoint directly from the spec |

The `call` command also accepts `--token`, `--username`, `--password`, and `--base-url` for authentication.

## License

[MIT](LICENSE)
