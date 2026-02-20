# CLI reference

Complete reference for all `spectral` commands.

## Global

```
spectral [--version] [--help] <command>
```

## analyze

Analyze a capture bundle and produce API specifications.

```
spectral analyze <capture_path> -o <name> [--model MODEL] [--debug] [--skip-enrich]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `capture_path` | Yes | — | Path to the capture bundle (.zip) |
| `-o, --output` | Yes | — | Output base name (produces `<name>.yaml`, `<name>.graphql`, `<name>.restish.json`, `<name>-auth.py` as appropriate) |
| `--model` | No | `claude-sonnet-4-5-20250929` | Anthropic model to use for LLM steps |
| `--debug` | No | Off | Save LLM prompts and responses to `debug/<timestamp>/` |
| `--skip-enrich` | No | Off | Skip LLM enrichment (faster, but no business descriptions) |

The command auto-detects the protocol from captured traces. REST traces produce an OpenAPI 3.1 YAML file; GraphQL traces produce an SDL schema. A single capture can contain both protocols.

Requires the `ANTHROPIC_API_KEY` environment variable (loaded automatically from `.env`).

---

## capture inspect

Display summary or detailed information about a capture bundle.

```
spectral capture inspect <capture_path> [--trace ID]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `capture_path` | Yes | — | Path to the capture bundle (.zip) |
| `--trace` | No | — | Show detailed info for a specific trace (e.g., `t_0001`) |

Without `--trace`, shows a summary: capture metadata, statistics (trace/WS/context counts), and a table of all traces with method, URL, status, and timing.

With `--trace`, shows the full detail for one trace: request headers and decoded body, response headers and decoded body, timing breakdown, and associated context references.

---

## capture proxy

Run a MITM proxy that captures traffic into a bundle.

```
spectral capture proxy [-p PORT] [-o PATH] [-d DOMAIN ...]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `-p, --port` | No | 8080 | Proxy listen port |
| `-o, --output` | No | `capture.zip` | Output bundle path |
| `-d, --domain` | No | (all domains) | Only intercept matching domains; repeatable. Supports glob patterns (e.g., `*.example.com`). |

Press `Ctrl+C` to stop the proxy. The bundle is written on exit with summary statistics.

The proxy requires the mitmproxy CA certificate to be trusted by the client. See [Certificate setup](../capture/certificate-setup.md).

---

## capture discover

Run a passthrough proxy that logs domains without intercepting traffic.

```
spectral capture discover [-p PORT]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `-p, --port` | No | 8080 | Proxy listen port |

Press `Ctrl+C` to see a summary table of discovered domains with request counts. Use the output to build `-d` filter lists for `capture proxy`.

---

## android list

List packages installed on a connected Android device.

```
spectral android list [filter]
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `filter` | No | (all) | Substring to filter package names |

---

## android pull

Pull an APK from a connected device.

```
spectral android pull <package> [-o PATH]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `package` | Yes | — | Package name (e.g., `com.spotify.music`) |
| `-o, --output` | No | `<package>.apk` or `<package>/` | Output path (file for single APK, directory for split APKs) |

---

## android patch

Patch an APK to trust user-installed CA certificates.

```
spectral android patch <apk_path> [-o PATH]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `apk_path` | Yes | — | Path to APK file or directory of split APKs |
| `-o, --output` | No | `<stem>-patched.apk` or `<dir>-patched/` | Output path |

Requires `apktool` and `java` on the system PATH. The patched APK is re-signed with a debug key.

---

## android install

Install an APK on a connected device.

```
spectral android install <apk_path>
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `apk_path` | Yes | — | Path to APK file or directory of split APKs |

---

## android cert

Push the mitmproxy CA certificate to a connected device.

```
spectral android cert [cert_path]
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `cert_path` | No | `~/.mitmproxy/mitmproxy-ca-cert.pem` | Path to the CA certificate file (.pem) |

After pushing, install the certificate on the device via **Settings > Security > Install from storage > CA certificate**.
