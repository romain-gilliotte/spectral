# Desktop and CLI apps

The MITM proxy captures traffic from any application that respects `HTTP_PROXY` / `HTTPS_PROXY` environment variables. It stores captures directly into managed storage using the same bundle format as the Chrome extension.

## Basic usage

Start the proxy and point your application at it:

```bash
spectral capture proxy -a myapp &
HTTPS_PROXY=http://127.0.0.1:8080 curl https://api.example.com/users
```

Press `Ctrl+C` to stop the proxy. It stores the capture in managed storage and prints summary statistics (trace count, WebSocket connections, messages).

## Domain filtering

By default the proxy intercepts all HTTPS traffic. To target specific domains, use the `-d` flag (repeatable):

```bash
spectral capture proxy -a myapp -d "api.example.com" -d "auth.example.com"
```

Glob-style patterns are supported:

```bash
spectral capture proxy -a myapp -d "*.example.com"
```

Traffic to non-matching domains passes through without interception.

## Domain discovery

If you don't know which domains an application talks to, use the discovery mode first:

```bash
spectral capture discover
```

This runs a passthrough proxy that does not perform MITM — all connections pass through untouched. It logs TLS SNI hostnames and plain HTTP host headers. Press `Ctrl+C` to see a summary table of discovered domains with request counts.

Use the output to build your `-d` filter list for the actual capture.

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `-a, --app` | (prompted) | App name for managed storage |
| `-p, --port` | 8080 | Proxy listen port |
| `-d, --domain` | (all) | Domain filter pattern (repeatable) |

## Certificate setup

The proxy intercepts HTTPS by generating certificates on the fly, signed by the mitmproxy CA. For this to work, the CA certificate must be trusted by the operating system or application making the requests.

On first run, mitmproxy creates its CA in `~/.mitmproxy/`. The file you need to install is `mitmproxy-ca-cert.pem`.

### Generate the CA certificate

Run mitmproxy once to generate its CA:

```bash
mitmproxy
```

Then quit (`q`, `y`). The CA files are created in `~/.mitmproxy/`.

### macOS

Add the certificate to the system keychain and mark it as trusted:

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/.mitmproxy/mitmproxy-ca-cert.pem
```

Alternatively, open Keychain Access, import the certificate, double-click it, expand "Trust", and set "When using this certificate" to "Always Trust".

### Linux (Debian/Ubuntu)

Copy the certificate and update the trust store:

```bash
sudo cp ~/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt
sudo update-ca-certificates
```

!!! note
    The file must have a `.crt` extension for `update-ca-certificates` to pick it up.

### Linux (Fedora/RHEL)

```bash
sudo cp ~/.mitmproxy/mitmproxy-ca-cert.pem /etc/pki/ca-trust/source/anchors/mitmproxy.pem
sudo update-ca-trust
```

### Verification

After installing the certificate, verify that the proxy can intercept HTTPS:

```bash
spectral capture proxy &
HTTPS_PROXY=http://127.0.0.1:8080 curl -I https://example.com
```

If the `curl` command succeeds without certificate errors, the setup is correct. If you see a certificate verification error, the CA is not properly trusted by the system or application.

## Limitations

The MITM proxy does not capture UI context (clicks, page content, etc.) — that information only comes from the Chrome extension. Captures produced by the proxy contain network traces and WebSocket data but no context events.

The analysis pipeline still works on proxy-only captures, but the LLM has less context to infer business semantics. For the best results, use the Chrome extension for web applications and reserve the proxy for non-browser traffic (mobile apps, CLI tools, desktop applications).
