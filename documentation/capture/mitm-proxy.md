# MITM proxy

The MITM proxy captures traffic from any application that respects `HTTP_PROXY` / `HTTPS_PROXY` environment variables. It produces the same capture bundle format as the Chrome extension.

## Basic usage

Start the proxy and point your application at it:

```bash
uv run spectral capture proxy -o capture.zip &
HTTPS_PROXY=http://127.0.0.1:8080 curl https://api.example.com/users
```

Press `Ctrl+C` to stop the proxy. It writes the capture bundle and prints summary statistics (trace count, WebSocket connections, messages).

## Domain filtering

By default the proxy intercepts all HTTPS traffic. To target specific domains, use the `-d` flag (repeatable):

```bash
uv run spectral capture proxy -d "api.example.com" -d "auth.example.com" -o capture.zip
```

Glob-style patterns are supported:

```bash
uv run spectral capture proxy -d "*.example.com" -o capture.zip
```

Traffic to non-matching domains passes through without interception.

## Domain discovery

If you don't know which domains an application talks to, use the discovery mode first:

```bash
uv run spectral capture discover
```

This runs a passthrough proxy that does not perform MITM — all connections pass through untouched. It logs TLS SNI hostnames and plain HTTP host headers. Press `Ctrl+C` to see a summary table of discovered domains with request counts.

Use the output to build your `-d` filter list for the actual capture.

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `-p, --port` | 8080 | Proxy listen port |
| `-o, --output` | `capture.zip` | Output bundle path |
| `-d, --domain` | (all) | Domain filter pattern (repeatable) |

## Certificate trust

The proxy intercepts HTTPS by generating certificates on the fly, signed by the mitmproxy CA. For this to work, the CA certificate must be trusted by the application or operating system making the requests.

On first run, mitmproxy creates its CA in `~/.mitmproxy/`. See [Certificate setup](certificate-setup.md) for instructions on installing it in your OS or browser trust store.

## Limitations

The MITM proxy does not capture UI context (clicks, page content, etc.) — that information only comes from the Chrome extension. Bundles produced by the proxy contain network traces and WebSocket data but no context events.

The analysis pipeline still works on proxy-only bundles, but the LLM has less context to infer business semantics. For the best results, use the Chrome extension for web applications and reserve the proxy for non-browser traffic (mobile apps, CLI tools, desktop applications).
