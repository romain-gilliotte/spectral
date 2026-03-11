# CLI reference

Complete reference for all `spectral` commands.

## Global

```
spectral [--version] [--help] <command>
```

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

## android list

List packages installed on a connected Android device.

```
spectral android list [filter]
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `filter` | No | (all) | Substring to filter package names |

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

## auth analyze

Analyze captures to detect authentication mechanisms and generate an auth script.

```
spectral auth analyze <app_name> [--debug]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `--debug` | No | Off | Save LLM prompts and responses to `debug/<timestamp>/` |

Examines all traces for auth-related patterns (login endpoints, token exchanges, OAuth flows) and generates `auth_acquire.py` in the app's managed storage directory. The script contains `acquire_token()` and optionally `refresh_token()` functions.

If no authentication mechanism is detected, prints an informational message and exits without generating a script.

Requires an Anthropic API key (resolved from `config.json` in managed storage — run `spectral config` to set up).

---

## auth extract

Extract auth tokens directly from captured traces without generating a script.

```
spectral auth extract <app_name> [--debug]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `--debug` | No | Off | Save LLM prompts and responses to `debug/<timestamp>/` |

Scans all traces for auth headers (Authorization, cookies, etc.) and writes them to `token.json`. Tries a fast path first (looks for `Authorization` headers directly), falling back to the LLM to identify other auth headers if needed.

This is the quickest way to get a working token when you already have authenticated traffic in your captures. Unlike `auth analyze`, it does not generate a reusable script — it extracts the token values observed in the traces.

Requires an Anthropic API key only when the fast path fails and LLM analysis is needed.

---

## auth login

Run interactive authentication for an app.

```
spectral auth login <app_name> [--debug]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `--debug` | No | Off | Save LLM prompts and responses to `debug/<timestamp>/` |

Loads the generated `auth_acquire.py` script, calls `acquire_token()` (which prompts for credentials), and writes the result to `token.json`.

If the script fails, the command offers to fix it interactively using the LLM. When accepted, it enters a fix loop: the LLM receives the error (including any script debug output), rewrites the script, and retries login automatically until it succeeds or the user cancels.

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

## capture list

List all known apps with capture counts.

```
spectral capture list
```

Shows a table of all apps in managed storage with their display name, number of captures, and last update time.

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

The proxy requires the mitmproxy CA certificate to be trusted by the client. See [Desktop and CLI apps — Certificate setup](../capture/desktop.md#certificate-setup).

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

## completion

Generate a shell completion script for bash or zsh. The script enables tab-completion for all commands, subcommands, options, and app names.

```
spectral completion bash|zsh
```

| Argument | Required | Description |
|----------|----------|-------------|
| `shell` | Yes | Target shell: `bash` or `zsh` |

Add the output to your shell profile to enable persistent completion:

- **bash** — add `eval "$(spectral completion bash)"` to `~/.bashrc`
- **zsh** — add `eval "$(spectral completion zsh)"` to `~/.zshrc`

App names are completed dynamically from managed storage.

---

## config

Configure the Anthropic API key and LLM model used by analyze commands.

```
spectral config
```

Prompts for the API key and model, then writes them to `config.json` in managed storage. If a config already exists, the current values are shown and used as defaults.

---

## extension install

Install the Chrome Native Messaging host manifest so the extension can send captures directly to the CLI.

```
spectral extension install --extension-id <ID> [--browser BROWSER]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--extension-id` | Yes | — | Chrome extension ID (from `chrome://extensions`) |
| `--browser` | No | (auto-detect) | Target browser: `chrome`, `chromium`, `brave`, `edge`. By default, writes manifests for all detected browsers. |

Writes a native messaging host manifest (`com.spectral.capture_host.json`) and a wrapper script (`~/.local/share/spectral/native_host.sh`). The wrapper invokes `spectral extension listen`.

---

## extension listen

Native messaging host process (called by Chrome, not by users directly).

```
spectral extension listen
```

Reads one length-prefixed JSON message from stdin, stores the capture in managed storage, writes a response to stdout, and exits. Chrome spawns this process automatically via `sendNativeMessage()`.

---

## graphql analyze

Analyze all captures for an app and produce a GraphQL SDL schema.

```
spectral graphql analyze <app_name> -o <name> [--debug] [--skip-enrich]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `-o, --output` | Yes | — | Output base name (produces `<name>.graphql`) |
| `--debug` | No | Off | Save LLM prompts and responses to `debug/<timestamp>/` |
| `--skip-enrich` | No | Off | Skip LLM enrichment (faster, but no business descriptions) |

The command loads all captures for the app and merges them into a single bundle before analysis. Only GraphQL traces are processed; REST traces are ignored.

Requires an Anthropic API key (resolved from `config.json` in managed storage — run `spectral config` to set up).

---

## mcp analyze

Generate MCP tool definitions from captures.

```
spectral mcp analyze <app_name> [--debug] [--skip-enrich]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `--debug` | No | Off | Save LLM prompts and responses to `debug/<timestamp>/` |
| `--skip-enrich` | No | Off | Skip LLM enrichment (faster, but no business descriptions) |

Writes tool definitions to `tools/*.json` in the app's managed storage directory and updates `app.json` with the detected `base_url`.

Requires an Anthropic API key (resolved from `config.json` in managed storage — run `spectral config` to set up).

---

## mcp install

Register the MCP server in Claude Desktop and/or Claude Code.

```
spectral mcp install [--target TARGET]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--target` | No | (all detected) | Target client: `claude-desktop` or `claude-code` |

Without `--target`, auto-detects installed clients and registers the server with each. The command resolves the absolute path to the `spectral` executable so the server works regardless of shell PATH.

For Claude Desktop, writes to `claude_desktop_config.json`. For Claude Code, runs `claude mcp add -s user spectral`.

---

## mcp stdio

Start the MCP server on stdio.

```
spectral mcp stdio
```

Exposes all app tools from managed storage as MCP tools. This is the command users configure in their MCP client (Claude Desktop, Claude Code, etc.).

---

## openapi analyze

Analyze all captures for an app and produce an OpenAPI specification.

```
spectral openapi analyze <app_name> -o <name> [--debug] [--skip-enrich]
```

| Argument / Option | Required | Default | Description |
|-------------------|----------|---------|-------------|
| `app_name` | Yes | — | Name of the app in managed storage |
| `-o, --output` | Yes | — | Output base name (produces `<name>.yaml`) |
| `--debug` | No | Off | Save LLM prompts and responses to `debug/<timestamp>/` |
| `--skip-enrich` | No | Off | Skip LLM enrichment (faster, but no business descriptions) |

The command loads all captures for the app and merges them into a single bundle before analysis. Only REST traces are processed; GraphQL traces are ignored.

Requires an Anthropic API key (resolved from `config.json` in managed storage — run `spectral config` to set up).
