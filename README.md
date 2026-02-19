<p align="center">
  <img src="assets/banner.png" alt="Spectral" width="600">
</p>

Reverse-engineer any app's private API. Browse normally, get a full spec — then use it to build AI agents and automations instead of brittle browser scripts.

Most apps sit on undocumented APIs that work perfectly well. But without a spec, people fall back to Playwright/Selenium/Puppeteer: slow, fragile, breaks on every UI change, can't handle mobile. Spectral captures the traffic, has an LLM figure out what each call means, and gives you a spec you can actually use.

Supports both **REST** (outputs OpenAPI 3.1) and **GraphQL** (outputs SDL with inferred types).

## How it works

1. **Capture** — Chrome extension (web) or MITM proxy records traffic + UI actions while you browse
2. **Analyze** — LLM correlates UI actions with API calls, infers endpoint patterns, auth flow, and business meaning. REST traces produce an OpenAPI 3.1 spec; GraphQL traces produce a typed SDL schema

## Quick start

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), [Anthropic API key](https://console.anthropic.com/).

```bash
git clone https://github.com/eloims/spectral.git && cd spectral
uv sync
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

uv run spectral analyze capture.zip -o spec
```

## Capture

### Web (Chrome Extension)

1. Load `extension/` as unpacked in `chrome://extensions`
2. Start capture, browse the app, stop capture, export bundle

### MITM proxy

### On your machine

The MITM proxy works with any application or CLI that respects `HTTP_PROXY` / `HTTPS_PROXY`:

```bash
uv run spectral capture proxy -o capture.zip &
HTTPS_PROXY=http://127.0.0.1:8080 curl https://api.example.com/users
```

The proxy intercepts HTTPS by generating certificates on the fly. For this to work, the mitmproxy CA certificate must be trusted by your machine. On first run, mitmproxy creates its CA in `~/.mitmproxy/` — install `mitmproxy-ca-cert.pem` in your OS/browser trust store.

Use `capture discover` to log domains first without intercepting, then `capture proxy -d` to target specific domains.

#### Android

Requires `adb` (Android SDK Platform Tools) and `java` (for APK signing) on the host machine.

On Android 7+, apps only trust system CA certificates by default and ignore user-installed ones. To intercept an app's HTTPS traffic, you need to patch its APK to add a network security config that trusts user CAs, then push the mitmproxy certificate to the device.

```bash
# Patch any app
uv run spectral android list spotify
uv run spectral android pull com.spotify.music
uv run spectral android patch com.spotify.music.apk
uv run spectral android install com.spotify.music-patched.apk

# Push the certificate to the device storage
uv run spectral android cert
```

Once the patched app is installed and the certificate is in place, configure the device to use the proxy (`Settings > Wi-Fi > proxy`) and capture traffic with `capture proxy` as usual.

## CLI reference

### Analyze

```
spectral analyze <bundle> -o <name> [--model MODEL] [--debug] [--skip-enrich]
```

The pipeline auto-detects the protocol from captured traces and produces `<name>.yaml` (OpenAPI 3.1) for REST and/or `<name>.graphql` (SDL) for GraphQL. A single capture can contain both.

| Option          | Default                      | Description                      |
| --------------- | ---------------------------- | -------------------------------- |
| `--model`       | `claude-sonnet-4-5-20250929` | LLM model                        |
| `--debug`       | off                          | Save LLM prompts to `debug/`     |
| `--skip-enrich` | off                          | Skip business context enrichment |

### Capture

| Command                                            | Description                                 |
| -------------------------------------------------- | ------------------------------------------- |
| `capture inspect <bundle> [--trace ID]`            | Inspect a capture bundle                    |
| `capture proxy [-d domain...] [-p port] [-o path]` | MITM proxy capture (all domains by default) |
| `capture discover [-p port]`                       | Discover domains without intercepting       |

### Android

| Command                            | Description                      |
| ---------------------------------- | -------------------------------- |
| `android list [filter]`            | List packages on device          |
| `android pull <package> [-o path]` | Pull APK(s) from device          |
| `android patch <apk> [-o path]`    | Patch APK to trust user CA certs |
| `android install <apk>`            | Install patched APK              |
| `android cert [cert_path]`         | Push CA certificate to device    |

## License

[MIT](LICENSE)
