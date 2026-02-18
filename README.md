<p align="center">
  <img src="assets/banner.png" alt="Spectral" width="600">
</p>

Reverse-engineer any app's private API. Browse normally, get a full API spec — then use it to build AI agents and automations instead of brittle browser scripts.

Most apps sit on undocumented APIs that work perfectly well. But without a spec, people fall back to Playwright/Selenium/Puppeteer: slow, fragile, breaks on every UI change, can't handle mobile. Spectral captures the traffic, has an LLM figure out what each call means, and gives you a spec you can actually use.

## How it works

1. **Capture** — Chrome extension (web) or MITM proxy (Android) records traffic + UI actions while you browse
2. **Analyze** — LLM correlates UI actions with API calls, infers endpoint patterns, auth flow, and business meaning
3. **Generate** — outputs OpenAPI 3.1, MCP server, Python client, markdown docs, or cURL scripts

## Quick start

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), [Anthropic API key](https://console.anthropic.com/).

```bash
git clone https://github.com/eloims/spectral.git && cd spectral
uv sync
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

uv run spectral analyze capture.zip -o spec.json
uv run spectral generate spec.json --type openapi -o openapi.yaml
```

## Capture

### Web (Chrome Extension)

1. Load `extension/` as unpacked in `chrome://extensions`
2. Start capture, browse the app, stop capture, export bundle

### Android

```bash
uv run spectral android list spotify
uv run spectral android pull com.spotify.music
uv run spectral android patch com.spotify.music.apk
uv run spectral android install com.spotify.music-patched.apk
uv run spectral android cert
uv run spectral capture proxy -d "api\.spotify\.com" -o spotify.zip
```

Run `spectral capture proxy` without `-d` first for discovery mode (logs domains without intercepting).

## CLI reference

### Capture

| Command | Description |
|---|---|
| `capture inspect <bundle> [--trace ID]` | Inspect a capture bundle |
| `capture proxy [-d domain...] [-p port] [-o path]` | MITM proxy capture |

### Android

| Command | Description |
|---|---|
| `android list [filter]` | List packages on device |
| `android pull <package> [-o path]` | Pull APK(s) from device |
| `android patch <apk> [-o path]` | Patch APK to trust user CA certs |
| `android install <apk>` | Install patched APK |
| `android cert [cert_path]` | Push CA certificate to device |

### Analyze

```
spectral analyze <bundle> -o spec.json [--model MODEL] [--debug] [--skip-enrich]
```

| Option | Default | Description |
|---|---|---|
| `--model` | `claude-sonnet-4-5-20250929` | LLM model |
| `--debug` | off | Save LLM prompts to `debug/` |
| `--skip-enrich` | off | Skip business context enrichment |

### Generate

```
spectral generate <spec> --type <type> -o <path>
```

Types: `openapi`, `mcp-server`, `python-client`, `markdown-docs`, `curl-scripts`

### Utilities

| Command | Description |
|---|---|
| `call <spec> --list` | List discovered endpoints |
| `call <spec> <endpoint> [key=value...]` | Call an endpoint from the spec |

`call` also accepts `--token`, `--username`, `--password`, `--base-url`.

## License

[MIT](LICENSE)
