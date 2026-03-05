# Spectral — Project Specification

## Style preferences

- **No code samples in documentation.** Documentation files should describe concepts in prose and tables, not paste code. The code lives in the code.

## Development environment

- Package manager is **uv**. Use `uv run` to execute commands (no need to activate the venv):
  - `uv run pytest tests/` — run tests
  - `uv run spectral mcp analyze ...` — run the CLI
  - `uv add <package>` — add a dependency (updates `pyproject.toml` + `uv.lock`)
  - `uv add --dev <package>` — add a dev dependency
- The Anthropic API key is resolved in order: `ANTHROPIC_API_KEY` env var → stored key at `~/.local/share/spectral/api_key` → interactive prompt. No `.env` file needed.
- **Before finishing any code change**, run the full verification suite and fix any new errors:
  - `uv run pytest tests/ -x -q` — all tests must pass
  - `uv run ruff check` — zero lint errors (use `--fix` for auto-fixable import sorting)
  - `uv run pyright` — zero new type errors (pre-existing errors in `proxy.py`, `test_proxy.py` are known)

## What this project is

A three-stage pipeline that automatically discovers, documents, and exposes web application APIs:

1. **Capture** — A Chrome Extension or MITM proxy records network traffic + UI actions while the user browses normally
2. **Analyze** — A CLI tool correlates UI actions with API calls using an LLM. REST traces produce an OpenAPI 3.1 spec; GraphQL traces produce a typed SDL schema. Both are enriched with business semantics
3. **Use** — Generated MCP tools let AI agents call the discovered API directly. Auth scripts handle token acquisition and refresh automatically

The key innovation is the **correlation of UI actions with network traffic** to understand the *business meaning* of each API call, not just its technical shape.

## Project structure

```
spectral/
├── extension/              # Chrome Extension (Manifest V3)
│   ├── background/         # Service worker modules (background.js, network.js, websocket.js, graphql.js, capture.js, export.js)
│   ├── content/            # UI context capture (content.js)
│   ├── popup/              # Extension popup UI
│   └── lib/                # Bundled dependencies (JSZip)
├── cli/                    # Python CLI tool
│   ├── main.py             # Entry point: wires command groups
│   ├── commands/
│   │   ├── openapi/        # REST analysis → OpenAPI 3.1 YAML
│   │   ├── graphql/        # GraphQL analysis → SDL schema
│   │   ├── mcp/            # MCP tool generation and stdio server
│   │   ├── auth/           # Authentication management
│   │   ├── capture/        # Bundle parsing, inspect, MITM proxy
│   │   ├── analyze/        # Shared analysis engine (pipeline, steps, correlator, protocol, schemas)
│   │   └── android/        # Android APK tools (list, pull, patch, install, cert)
│   ├── formats/            # Pydantic models (capture_bundle, mcp_tool, app_meta)
│   └── helpers/            # Shared utilities (llm, storage, naming, console, http, auth_framework)
├── tests/                  # Mirrors cli/ structure
├── pyproject.toml
└── README.md
```

## Data model convention

| Pattern | Contents | Python construct |
|---------|----------|-----------------|
| `cli/formats/<name>.py` | Serialization models (external formats: capture bundle, API spec) | Pydantic `BaseModel` |
| `cli/commands/<package>/types.py` | Internal types passed between modules | `@dataclass` |

## Technology choices

- **Extension**: Vanilla JS, Chrome Manifest V3, Chrome DevTools Protocol (via `chrome.debugger`), JSZip for bundle export
- **CLI**: Python 3.11+, Click for CLI, Pydantic for data models
- **LLM**: Anthropic API (Claude Sonnet) for semantic analysis
- **Packaging**: pyproject.toml with `[project.scripts]` entry point for `spectral`

## CLI commands

```bash
# Analyze captures (requires ANTHROPIC_API_KEY)
spectral mcp analyze <app>                          # → MCP tool definitions in storage
spectral openapi analyze <app> -o <base>           # → <base>.yaml (OpenAPI 3.1)
spectral graphql analyze <app> -o <base>            # → <base>.graphql (SDL schema)

# Auth management
spectral auth analyze <app>                         # detect auth, generate script
spectral auth set <app> -H "Authorization: ..."     # manually set auth headers
spectral auth set <app> -c "session=abc"            # set cookies
spectral auth login/logout/refresh <app>            # interactive auth operations

# MCP server
spectral mcp stdio                                  # start MCP server on stdio

# Capture management
spectral capture add <zip> -a <app>                 # import ZIP into managed storage
spectral capture list / show <app>                  # list apps / show captures
spectral capture inspect <app> [--trace t_0001]     # inspect capture contents
spectral capture proxy -a <app> [-d "pattern"]      # MITM proxy → managed storage
spectral capture discover                           # log domains without MITM

# Android APK tools
spectral android list/pull/patch/install/cert       # APK manipulation + cert push
```

Default model is `claude-sonnet-4-5-20250929`. Options: `--model`, `--skip-enrich`, `--debug`.

## Dependencies

| Component | Dependencies |
|-----------|-------------|
| Extension | JSZip (bundled) |
| CLI | click, pydantic, anthropic, graphql-core, pyyaml, rich, requests, mitmproxy, jq, compact-json, mcp |
| Dev | pytest, pytest-cov, pytest-asyncio (asyncio_mode="auto"), pyright, ruff, mkdocs-material |

## Managed storage

Layout under `~/.local/share/spectral/` (overridable with `SPECTRAL_HOME`):

```
api_key                   # Anthropic API key (plain text, created on first prompt)
apps/<name>/
├── app.json              # AppMeta (name, display_name, base_url, timestamps)
├── auth_acquire.py       # Generated auth script (acquire_token, refresh_token)
├── token.json            # TokenState (headers, refresh_token, expires_at)
├── tools/<tool>.json     # ToolDefinition (name, description, parameters, request)
└── captures/<timestamp>_<source>_<id-prefix>/
    ├── manifest.json, traces/, ws/, contexts/, timeline.json
```

The storage layer (`cli/helpers/storage.py`) provides: `import_capture`, `store_capture`, `list_apps`, `list_captures`, `load_app_bundle` (load + merge all captures), `write_token` / `load_token` / `delete_token`, `write_tools` / `load_tools`, `auth_script_path`. Duplicate captures (same `capture_id`) are rejected.

Bundle merging (`merge_bundles` in `cli/commands/capture/types.py`) prefixes IDs with a 3-digit capture index to avoid collisions across sessions (e.g. `t_0001` from capture 2 becomes `t_002_0001`).

## Environment variables

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Override for analyze commands (otherwise read from `api_key` file or prompted) |
| `SPECTRAL_HOME` | Override managed storage root (default: `~/.local/share/spectral`) |

## Remaining work

- Real-world testing with actual API keys
- Prompt tuning for better enrichment quality
- Privacy controls: exclude domains, redact headers/cookies
