# CLI reference

Complete reference for all `spectral` commands.

## Global

```
spectral [--version] [--help] <command>
```

## openapi analyze

Analyze all captures for an app and produce an OpenAPI specification.

```
spectral openapi analyze <app_name> -o <name> [--model MODEL] [--debug] [--skip-enrich]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `-o, --output` | Yes | — | Output base name (produces `<name>.yaml` and `<name>.restish.json`) |
| `--model` | No | `claude-sonnet-4-5-20250929` | Anthropic model to use for LLM steps |
| `--debug` | No | Off | Save LLM prompts and responses to `debug/<timestamp>/` |
| `--skip-enrich` | No | Off | Skip LLM enrichment (faster, but no business descriptions) |

The command loads all captures for the app and merges them into a single bundle before analysis. Only REST traces are processed; GraphQL traces are ignored. REST traces produce an OpenAPI 3.1 YAML file and a Restish configuration file.

Requires the `ANTHROPIC_API_KEY` environment variable (loaded automatically from `.env`).

---

## graphql analyze

Analyze all captures for an app and produce a GraphQL SDL schema.

```
spectral graphql analyze <app_name> -o <name> [--model MODEL] [--debug] [--skip-enrich]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `-o, --output` | Yes | — | Output base name (produces `<name>.graphql`) |
| `--model` | No | `claude-sonnet-4-5-20250929` | Anthropic model to use for LLM steps |
| `--debug` | No | Off | Save LLM prompts and responses to `debug/<timestamp>/` |
| `--skip-enrich` | No | Off | Skip LLM enrichment (faster, but no business descriptions) |

The command loads all captures for the app and merges them into a single bundle before analysis. Only GraphQL traces are processed; REST traces are ignored.

Requires the `ANTHROPIC_API_KEY` environment variable (loaded automatically from `.env`).

---

## mcp analyze

Generate MCP tool definitions from captures.

```
spectral mcp analyze <app_name> [--model MODEL] [--debug] [--skip-enrich]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `--model` | No | `claude-sonnet-4-5-20250929` | Anthropic model to use for LLM steps |
| `--debug` | No | Off | Save LLM prompts and responses to `debug/<timestamp>/` |
| `--skip-enrich` | No | Off | Skip LLM enrichment (faster, but no business descriptions) |

Writes tool definitions to `tools/*.json` in the app's managed storage directory and updates `app.json` with the detected `base_url`.

Requires the `ANTHROPIC_API_KEY` environment variable (loaded automatically from `.env`).

---

## mcp stdio

Start the MCP server on stdio.

```
spectral mcp stdio
```

Exposes all app tools from managed storage as MCP tools. This is the command users configure in their MCP client (Claude Desktop, Claude Code, etc.).

---

## auth analyze

Analyze captures to detect authentication mechanisms and generate an auth script.

```
spectral auth analyze <app_name> [--model MODEL] [--debug]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `--model` | No | `claude-sonnet-4-5-20250929` | Anthropic model to use |
| `--debug` | No | Off | Save LLM prompts and responses to `debug/<timestamp>/` |

Examines all traces for auth-related patterns (login endpoints, token exchanges, OAuth flows) and generates `auth_acquire.py` in the app's managed storage directory. The script contains `acquire_token()` and optionally `refresh_token()` functions.

If no authentication mechanism is detected, prints an informational message and exits without generating a script.

Requires the `ANTHROPIC_API_KEY` environment variable (loaded automatically from `.env`).

---

## auth set

Manually set auth headers or cookies for an app.

```
spectral auth set <app_name> [-H HEADER ...] [-c COOKIE ...]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `-H, --header` | No | — | Header as `"Name: Value"` (repeatable) |
| `-c, --cookie` | No | — | Cookie as `"name=value"` (repeatable) |

Fallback when the generated auth script does not work. Pass headers and/or cookies directly to store in `token.json`. If neither `--header` nor `--cookie` is given, prompts for a token interactively and stores it as `Authorization: Bearer <token>`.

Cookies are joined into a single `Cookie` header (e.g., `-c "a=1" -c "b=2"` becomes `Cookie: a=1; b=2`).

---

## auth login

Run interactive authentication for an app.

```
spectral auth login <app_name>
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |

Loads the generated `auth_acquire.py` script, calls `acquire_token()` (which prompts for credentials), and writes the result to `token.json`.

---

## auth logout

Remove the stored token for an app.

```
spectral auth logout <app_name>
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |

---

## auth refresh

Manually refresh the auth token for an app.

```
spectral auth refresh <app_name>
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |

Loads `token.json`, calls `refresh_token()` from the auth script, and updates `token.json` with the new token. Requires both `token.json` and `auth_acquire.py` to exist.

---

## capture add

Import a ZIP bundle from the Chrome extension into managed storage.

```
spectral capture add <zip_file> [-a APP]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `zip_file` | Yes | — | Path to the capture bundle (.zip) |
| `-a, --app` | No | (prompted) | App name for storage. If omitted, prompted interactively with a suggestion derived from the bundle's app name. |

Duplicate captures (same `capture_id`) are detected and skipped. Multiple captures can be imported into the same app and are merged automatically during analysis.

---

## capture list

List all known apps with capture counts.

```
spectral capture list
```

Shows a table of all apps in managed storage with their display name, number of captures, and last update time.

---

## capture show

Show captures for an app.

```
spectral capture show <app_name>
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |

Lists each capture under the app with its creation time, capture method (extension or proxy), and statistics.

---

## capture inspect

Inspect the latest capture for an app.

```
spectral capture inspect <app_name> [--trace ID]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `--trace` | No | — | Show detailed info for a specific trace (e.g., `t_0001`) |

Without `--trace`, shows a summary: capture metadata, statistics (trace/WS/context counts), and a table of all traces with method, URL, status, and timing.

With `--trace`, shows the full detail for one trace: request headers and decoded body, response headers and decoded body, timing breakdown, and associated context references.

---

## capture proxy

Run a MITM proxy that captures traffic into managed storage.

```
spectral capture proxy [-a APP] [-p PORT] [-d DOMAIN ...]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `-a, --app` | No | (prompted) | App name for storage |
| `-p, --port` | No | 8080 | Proxy listen port |
| `-d, --domain` | No | (all domains) | Only intercept matching domains; repeatable. Supports glob patterns (e.g., `*.example.com`). |

Press `Ctrl+C` to stop the proxy. The capture is stored in managed storage on exit with summary statistics.

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
