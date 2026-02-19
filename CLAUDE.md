# Spectral — Project Specification

## Style preferences

- **No code samples in documentation.** Documentation files should describe concepts in prose and tables, not paste code. The code lives in the code.

## Development environment

- Package manager is **uv**. Use `uv run` to execute commands (no need to activate the venv):
  - `uv run pytest tests/` — run tests
  - `uv run spectral analyze ...` — run the CLI
  - `uv add <package>` — add a dependency (updates `pyproject.toml` + `uv.lock`)
  - `uv add --dev <package>` — add a dev dependency
- `.env` file at project root holds `ANTHROPIC_API_KEY` (loaded by the CLI via `python-dotenv`). Do NOT commit `.env`.
- **Before finishing any code change**, run the full verification suite and fix any new errors:
  - `uv run pytest tests/ -x -q` — all tests must pass
  - `uv run ruff check` — zero lint errors (use `--fix` for auto-fixable import sorting)
  - `uv run pyright` — zero new type errors (pre-existing errors in `proxy.py`, `test_proxy.py` are known)

## What this project is

A two-stage pipeline that automatically discovers and documents web application APIs:

1. **Capture** — A Chrome Extension or MITM proxy records network traffic + UI actions while the user browses normally
2. **Analyze** — A CLI tool correlates UI actions ↔ API calls using an LLM. REST traces produce an OpenAPI 3.1 spec; GraphQL traces produce a typed SDL schema. Both are enriched with business semantics

The key innovation is the **correlation of UI actions with network traffic** to understand the *business meaning* of each API call, not just its technical shape. No existing tool does this.

## Project structure

```
spectral/
├── extension/              # Chrome Extension (Manifest V3)
│   ├── manifest.json
│   ├── background/         # Service worker modules
│   │   ├── background.js   # Entry point: event listeners, message handler
│   │   ├── state.js        # Shared capture state, state machine enum
│   │   ├── utils.js        # Helpers (padId, uuid, now, base64 decode)
│   │   ├── network.js      # HTTP request/response capture via DevTools Protocol
│   │   ├── websocket.js    # WebSocket capture via DevTools Protocol
│   │   ├── graphql.js      # GraphQL interception via Fetch.requestPaused (detection, APQ rejection, __typename injection)
│   │   ├── capture.js      # Capture lifecycle (start, stop, stats, content script control)
│   │   └── export.js       # Bundle export: assemble ZIP and trigger download
│   ├── content/
│   │   └── content.js      # UI context capture (clicks, navigation, DOM state, page content)
│   ├── popup/
│   │   ├── popup.html      # Start/stop/export UI with live stats
│   │   ├── popup.js        # Popup controller (state management, polling)
│   │   └── popup.css       # Popup styling (320px popup, status indicators)
│   ├── lib/
│   │   ├── jszip.js        # ESM wrapper for jszip.min.js
│   │   └── jszip.min.js    # ZIP library for bundle export
│   └── icons/
│       ├── icon16.png
│       ├── icon48.png
│       └── icon128.png
├── cli/                    # Python CLI tool
│   ├── __init__.py
│   ├── main.py             # Entry point: commands (analyze, capture, android)
│   ├── commands/
│   │   ├── capture/         # Capture: bundle parsing, inspect, MITM proxy
│   │   │   ├── cmd.py       # CLI group: capture inspect, capture proxy, capture discover
│   │   │   ├── inspect.py   # Inspect implementation: summary + per-trace detail views
│   │   │   ├── proxy.py     # Generic MITM proxy engine (mitmproxy addons, run_proxy, run_discover)
│   │   │   ├── loader.py    # Unzips and loads a capture bundle (+ write_bundle)
│   │   │   ├── graphql_utils.py # GraphQL __typename injection (AST visitor via graphql-core)
│   │   │   └── types.py     # Data classes for traces, contexts, timeline (wraps Pydantic + binary)
│   │   ├── analyze/         # Analysis engine
│   │   │   ├── cmd.py       # CLI command: analyze <bundle> -o <name> [--model] [--debug] [--skip-enrich]
│   │   │   ├── pipeline.py  # Orchestrator: build_spec() → REST (OpenAPI) and/or GraphQL (SDL)
│   │   │   ├── correlator.py# Time-window correlation: UI action → API calls
│   │   │   ├── protocol.py  # Protocol detection (REST, GraphQL, WebSocket, gRPC, binary)
│   │   │   ├── tools.py     # LLM tool loop, investigation tools
│   │   │   ├── utils.py     # Shared utilities (_pattern_to_regex, _compact_url, _sanitize_headers)
│   │   │   ├── schemas.py   # JSON schema inference, annotated schemas, format detection
│   │   │   └── steps/       # Pipeline steps (Step[In,Out] architecture)
│   │   │       ├── types.py            # Shared dataclasses (MethodUrlPair, AnalysisResult, etc.)
│   │   │       ├── base.py             # Step, LLMStep, MechanicalStep, StepValidationError
│   │   │       ├── detect_base_url.py  # LLMStep: identify business API base URL
│   │   │       ├── analyze_auth.py     # LLMStep: detect auth mechanism from all traces
│   │   │       ├── extract_pairs.py    # MechanicalStep: traces → (method, url) pairs
│   │   │       ├── filter_traces.py    # MechanicalStep: keep traces matching base URL
│   │   │       ├── rest/               # REST-specific steps
│   │   │       │   ├── types.py        # REST dataclasses (EndpointGroup, EndpointSpec, etc.)
│   │   │       │   ├── group_endpoints.py # LLMStep: group URLs into endpoint patterns
│   │   │       │   ├── strip_prefix.py    # MechanicalStep: remove base URL path prefix
│   │   │       │   ├── extraction.py      # MechanicalStep: groups → EndpointSpec[]
│   │   │       │   ├── enrich.py          # LLMStep: per-endpoint parallel enrichment
│   │   │       │   └── assemble.py        # MechanicalStep: combine all parts → OpenAPI 3.1 dict
│   │   │       └── graphql/            # GraphQL-specific steps
│   │   │           ├── types.py        # GraphQL dataclasses (TypeRecord, FieldRecord, etc.)
│   │   │           ├── parser.py       # Parse GraphQL queries from trace bodies
│   │   │           ├── extraction.py   # MechanicalStep: traces → TypeRegistry (type reconstruction)
│   │   │           ├── enrich.py       # LLMStep: per-type parallel enrichment
│   │   │           └── assemble.py     # MechanicalStep: TypeRegistry → SDL string
│   │   └── android/         # Android APK tools (pull, patch, install, cert)
│   │       ├── cmd.py       # CLI group: android list, pull, patch, install, cert
│   │       ├── adb.py       # ADB wrapper: list, pull, install, push cert
│   │       └── patch.py     # APK patching: network security config, signing
│   ├── formats/             # Shared format definitions
│   │   └── capture_bundle.py   # Capture bundle Pydantic models (17 models)
│   └── helpers/             # Shared utilities
│       ├── console.py       # Rich console instance
│       ├── llm.py           # Centralized LLM helper (rate-limit retry, concurrency control)
│       ├── naming.py        # safe_name(), to_identifier()
│       ├── subprocess.py    # run_subprocess() helper
│       └── http.py          # HTTP helpers
├── tests/                     # Mirrors cli/ directory structure
│   ├── conftest.py            # Shared fixtures (sample_bundle, make_trace, make_context, etc.)
│   ├── analyze/               # Tests for analyze command
│   │   ├── steps/
│   │   │   ├── graphql/       # GraphQL step tests (parser, extraction, enrich, assemble)
│   │   │   ├── rest/          # REST step tests (extraction, enrich, assemble)
│   │   │   ├── test_base.py   # Step base classes (Step, LLMStep, MechanicalStep)
│   │   │   └── test_detect_base_url.py
│   │   ├── test_correlator.py
│   │   ├── test_pipeline.py
│   │   ├── test_protocol.py
│   │   ├── test_schemas.py
│   │   └── test_tools.py
│   ├── android/               # ADB, patch, android CLI tests
│   ├── capture/               # Loader, proxy, graphql_utils tests
│   ├── cli/                   # CLI command tests
│   ├── formats/               # Pydantic model roundtrip tests
│   └── helpers/               # Naming, subprocess, HTTP, LLM helper tests
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

---

## FORMAT 1: Capture Bundle (.zip)

This is the custom format produced by the Chrome Extension. We chose a ZIP bundle over HAR because:
- HAR is JSON/UTF-8 only — no native binary support (would need base64, +33% overhead)
- HAR has no standard WebSocket support (Chrome uses non-standard `_webSocketMessages`)
- HAR has no concept of UI context or unique trace IDs for cross-referencing
- HAR's request/response pair model doesn't fit WebSocket's async full-duplex messages

### Bundle structure

```
capture_<timestamp>.zip
├── manifest.json              # Session metadata
├── traces/
│   ├── t_0001_request.bin     # Raw request body (binary-safe, may be empty)
│   ├── t_0001_response.bin    # Raw response body (binary-safe, may be empty)
│   ├── t_0001.json            # Trace metadata (headers, timing, status, URL, method)
│   ├── t_0002_request.bin
│   ├── t_0002_response.bin
│   ├── t_0002.json
│   └── ...
├── ws/                        # WebSocket messages (one file per message)
│   ├── ws_0001.json           # WS connection metadata (handshake headers, URL)
│   ├── ws_0001_m001.bin       # Message 1 payload (binary-safe)
│   ├── ws_0001_m001.json      # Message 1 metadata (direction, timestamp, opcode)
│   ├── ws_0001_m002.bin
│   ├── ws_0001_m002.json
│   └── ...
├── contexts/
│   ├── c_0001.json            # UI context snapshot (with rich page content)
│   ├── c_0002.json
│   └── ...
└── timeline.json              # Ordered list of all events with cross-references
```

### manifest.json

```json
{
  "format_version": "1.0.0",
  "capture_id": "a1b2c3d4-...",
  "created_at": "2026-02-13T15:30:00Z",
  "app": {
    "name": "EDF Customer Portal",
    "base_url": "https://www.edf.fr",
    "title": "EDF - Mon espace client"
  },
  "browser": {
    "name": "Chrome",
    "version": "133.0.6943.98"
  },
  "extension_version": "0.1.0",
  "duration_ms": 45000,
  "stats": {
    "trace_count": 87,
    "ws_connection_count": 2,
    "ws_message_count": 34,
    "context_count": 12
  }
}
```

### Trace metadata — traces/t_NNNN.json

```json
{
  "id": "t_0001",
  "timestamp": 1739456400000,
  "type": "http",
  "request": {
    "method": "POST",
    "url": "https://api.edf.fr/api/consumption/monthly",
    "headers": [
      { "name": "Content-Type", "value": "application/json" },
      { "name": "Authorization", "value": "Bearer ey..." }
    ],
    "body_file": "t_0001_request.bin",
    "body_size": 42,
    "body_encoding": null
  },
  "response": {
    "status": 200,
    "status_text": "OK",
    "headers": [
      { "name": "Content-Type", "value": "application/json; charset=utf-8" }
    ],
    "body_file": "t_0001_response.bin",
    "body_size": 1523,
    "body_encoding": null
  },
  "timing": {
    "dns_ms": 2,
    "connect_ms": 15,
    "tls_ms": 12,
    "send_ms": 1,
    "wait_ms": 120,
    "receive_ms": 8,
    "total_ms": 158
  },
  "initiator": {
    "type": "script",
    "url": "https://www.edf.fr/assets/app.js",
    "line": 1234
  },
  "context_refs": ["c_0003"]
}
```

Key design decisions:
- **`id`** is a stable string (`t_NNNN`) — contexts, timeline, and analysis can reference it
- **`body_file`** points to the companion `.bin` file — binary-safe, no base64
- **`body_encoding`** is null for raw binary; set to `"base64"` only if the body was originally base64 in the protocol
- **`context_refs`** links to UI context(s) active when this trace was captured (via time-window matching done in the extension)
- **Headers are arrays, not objects** — HTTP allows duplicate header names

### WebSocket metadata — ws/ws_NNNN.json (connection)

```json
{
  "id": "ws_0001",
  "timestamp": 1739456400500,
  "url": "wss://realtime.edf.fr/socket",
  "handshake_trace_ref": "t_0015",
  "protocols": ["graphql-ws"],
  "message_count": 34,
  "context_refs": ["c_0004"]
}
```

### WebSocket message metadata — ws/ws_NNNN_mNNN.json

```json
{
  "id": "ws_0001_m001",
  "connection_ref": "ws_0001",
  "timestamp": 1739456401200,
  "direction": "send",
  "opcode": "text",
  "payload_file": "ws_0001_m001.bin",
  "payload_size": 89,
  "context_refs": ["c_0004"]
}
```

- **`opcode`**: `"text"` | `"binary"` | `"ping"` | `"pong"` | `"close"`
- **`direction`**: `"send"` (client→server) | `"receive"` (server→client)
- **`payload_file`** points to the raw binary payload

### UI Context — contexts/c_NNNN.json

```json
{
  "id": "c_0001",
  "timestamp": 1739456399800,
  "action": "click",
  "element": {
    "selector": "nav[data-tab='consumption']",
    "tag": "NAV",
    "text": "Ma consommation",
    "attributes": {
      "data-tab": "consumption"
    },
    "xpath": "/html/body/div[2]/nav/div[3]"
  },
  "page": {
    "url": "https://www.edf.fr/dashboard",
    "title": "Mon espace client - EDF",
    "content": {
      "headings": ["Mon espace client", "Ma consommation", "Mes factures"],
      "navigation": ["Accueil", "Consommation", "Factures", "Contrat"],
      "main_text": "Bienvenue sur votre espace client EDF...",
      "forms": [{ "id": "search-form", "fields": ["query"], "submitLabel": "Rechercher" }],
      "tables": ["Mois | Consommation | Coût"],
      "alerts": []
    }
  },
  "viewport": {
    "width": 1440,
    "height": 900,
    "scroll_x": 0,
    "scroll_y": 200
  }
}
```

The `page.content` field provides rich page context for LLM analysis:
- **`headings`** — visible h1/h2/h3 elements (up to 10)
- **`navigation`** — links from nav/menu elements (up to 15)
- **`main_text`** — visible text from main content area (max 500 chars)
- **`forms`** — visible forms with field identifiers and submit labels (up to 5)
- **`tables`** — header rows from visible tables (up to 5)
- **`alerts`** — visible alerts/notifications/toasts (up to 5)

Captured UI actions:
- `click` — user clicks an element (walks up to nearest meaningful ancestor: button, link, input, etc.)
- `input` — user types in a field (value NOT captured for privacy — only field identity, debounced 300ms)
- `submit` — form submission
- `navigate` — page navigation (pushState, replaceState, popstate)

### timeline.json

```json
{
  "events": [
    { "timestamp": 1739456399800, "type": "context",   "ref": "c_0001" },
    { "timestamp": 1739456400000, "type": "trace",     "ref": "t_0001" },
    { "timestamp": 1739456400500, "type": "ws_open",   "ref": "ws_0001" },
    { "timestamp": 1739456401200, "type": "ws_message", "ref": "ws_0001_m001" },
    { "timestamp": 1739456401500, "type": "trace",     "ref": "t_0002" },
    { "timestamp": 1739456402000, "type": "context",   "ref": "c_0002" }
  ]
}
```

This flat timeline makes correlation trivial: to find which API calls relate to a UI action, scan forward from the context event within a time window.

---

## FORMAT 2: Analysis Output

The pipeline auto-detects the protocol and produces the appropriate output format:

- **REST** → OpenAPI 3.1 YAML (`.yaml`), enriched with LLM-inferred business semantics in standard OpenAPI fields (`summary`, `description`) and `x-` extensions (e.g. `x-rate-limit`). Built through REST-specific dataclasses (`cli/commands/analyze/steps/rest/types.py`): `EndpointSpec`, `RequestSpec`, `ResponseSpec`. The `AssembleStep` converts these into the final OpenAPI dict.
- **GraphQL** → SDL schema (`.graphql`), with type/field descriptions inferred by the LLM. Built by reconstructing types from captured queries and responses (using `__typename` injection), then rendered to SDL by the `GraphQLAssembleStep`.

A single capture can contain both REST and GraphQL traces; the pipeline processes them in parallel and writes both output files.

### What the LLM infers (Stage 2 — analyze)

The LLM is called during `spectral analyze` to produce these fields that a purely mechanical tool could not:

- Operation `summary` — what the endpoint does in business terms
- Response `description` — what each status code means in domain terms
- Schema property `description` — what a parameter/field means
- `auth.user_journey` — the authentication flow described for humans
- `auth.business_process` — how users obtain credentials

Everything else is mechanical (headers, schemas, status codes, URLs, timing).

---

## CLI commands

```bash
# Analyze a capture bundle → edf-api.yaml and/or edf-api.graphql (requires ANTHROPIC_API_KEY)
spectral analyze capture_20260213.zip -o edf-api
spectral analyze capture_20260213.zip -o edf-api --model claude-sonnet-4-5-20250929
spectral analyze capture_20260213.zip -o edf-api --skip-enrich  # skip LLM enrichment
spectral analyze capture_20260213.zip -o edf-api --debug        # save LLM prompts to debug/

# Capture: inspect bundles, run MITM proxy
spectral capture inspect capture_20260213.zip                    # summary stats
spectral capture inspect capture_20260213.zip --trace t_0001     # details of one trace
spectral capture proxy -o capture.zip                            # MITM all domains
spectral capture proxy -d "api\.example\.com" -o capture.zip     # MITM matching domains only
spectral capture discover                                        # log domains without MITM

# Android: APK tools
spectral android list spotify
spectral android pull com.spotify.music
spectral android patch com.spotify.music.apk
spectral android install com.spotify.music-patched.apk
spectral android cert                                            # push mitmproxy CA cert to device
```

Note: `analyze` requires `ANTHROPIC_API_KEY`. The `-o` flag takes a base name (e.g. `-o edf-api` produces `edf-api.yaml` and/or `edf-api.graphql`). Default model is `claude-sonnet-4-5-20250929`.

---

## Chrome Extension behavior

### Capture flow

1. User clicks "Start Capture" in extension popup
2. Extension attaches `chrome.debugger` to the active tab
3. `background/background.js` dispatches DevTools Protocol events to specialized modules:
   - `network.js` — HTTP request/response capture (headers, bodies, timing)
   - `websocket.js` — WebSocket connection and message capture
   - `graphql.js` — intercepts GraphQL requests via `Fetch.requestPaused` (detection, persisted query rejection, `__typename` injection)
4. `content/content.js` listens to DOM events (click, input, submit) and navigation events, extracts rich page content
5. Content script sends timestamped context events to background via `chrome.runtime.sendMessage`
6. On full-page navigation (non-SPA), `chrome.tabs.onUpdated` re-injects content script automatically so UI capture continues
7. User clicks "Stop Capture" → background detaches debugger
7. User clicks "Export" → background assembles the ZIP bundle using JSZip and triggers download

### Extension state machine

`IDLE` → `ATTACHING` → `CAPTURING` → `EXPORTING` → `IDLE`

The popup polls the background for current state and stats, updating the UI accordingly:
- **idle**: Show "Start Capture" button
- **capturing**: Show live stats (requests, WS messages, UI events, duration) + "Stop Capture" button
- **stopped**: Show final stats + "Export Bundle" button

### What we capture via DevTools Protocol

| Protocol event | What we get |
|---|---|
| `Network.requestWillBeSent` | URL, method, provisional headers, POST body, initiator, timestamp |
| `Network.requestWillBeSentExtraInfo` | Wire-level request headers (Cookie, browser-managed Authorization) |
| `Network.responseReceived` | Status, provisional headers, MIME type, timing |
| `Network.responseReceivedExtraInfo` | Wire-level response headers (Set-Cookie, cross-origin headers) |
| `Network.getResponseBody` | Full response body (text or base64-encoded binary) |
| `Network.webSocketCreated` | WebSocket URL |
| `Network.webSocketFrameSent` | Outgoing WS message (text or binary as base64) |
| `Network.webSocketFrameReceived` | Incoming WS message (text or binary as base64) |
| `Network.webSocketClosed` | WS connection closed |
| `Fetch.requestPaused` | Intercept all POST requests; detect GraphQL, reject persisted queries (APQ), inject `__typename` |

### What we capture via content script

| DOM event | What we record |
|---|---|
| `click` | Element selector, tag, text content, attributes, page URL, page content |
| `input` | Field identity (name, id, selector) — NOT the value (privacy), debounced 300ms |
| `submit` | Form target element |
| `pushState` / `replaceState` / `popstate` | Navigation URL changes (SPA) |

The content script also captures **rich page content** with each context event:
- Visible headings (h1-h3), navigation links, main text content
- Form field identifiers and submit labels
- Table headers, alerts/notifications

### Selector generation strategy

The content script generates stable CSS selectors using a priority chain:
1. Stable `id` attributes (filters out framework-generated IDs like `ember123`, `react-...`)
2. `data-testid` / `data-test` / `data-cy` attributes
3. Tag + `name` attribute for form elements
4. Fallback: tag + stable classes (filters framework CSS classes) + nth-child, up to 5 levels

### Context↔Trace correlation (in extension)

When storing a trace, the extension finds the most recent context(s) within a 2-second lookback window and writes their IDs into `context_refs`. This is a rough first-pass correlation — the CLI's analyze step refines it with LLM reasoning.

---

## Analysis pipeline (Step-based architecture)

The `build_spec()` function in `pipeline.py` orchestrates a Step-based pipeline. Each step is a typed `Step[In, Out]` with `run()` method, optional validation, and retry for LLM steps.

**Common steps** (sequential):
1. **Extract pairs** — `MechanicalStep`: collect `(method, url)` pairs from all traces
2. **Detect base URL** — `LLMStep`: identify the business API origin (with investigation tools, call frequency hints)
3. **Filter traces** — `MechanicalStep`: keep only traces matching the base URL
4. **Split by protocol** — traces are separated into REST and GraphQL groups

**REST branch** (when REST traces are present):
1. **Group endpoints** — `LLMStep`: group URLs into endpoint patterns with `{param}` syntax
2. **Strip prefix** — `MechanicalStep`: remove base URL path prefix from patterns
3. **Mechanical extraction** — `MechanicalStep`: build `EndpointSpec[]` with schemas, params
4. **Detect auth & rate limit** — mechanical per-endpoint detection from trace headers
5. **Enrich endpoints** — `LLMStep`: N parallel per-endpoint LLM calls for business semantics (via `asyncio.gather`)
6. **Auth analysis** — `LLMStep`: detect auth mechanism from ALL unfiltered traces (runs in parallel with enrichment)
7. **Assembly** — `MechanicalStep`: combine all outputs into OpenAPI 3.1 dict

**GraphQL branch** (when GraphQL traces are present):
1. **Extraction** — `MechanicalStep`: parse queries via `graphql-core`, walk response data with `__typename` to reconstruct a `TypeRegistry` (object types, input types, enums, scalars, field nullability/list-ness)
2. **Enrich types** — `LLMStep`: N parallel per-type LLM calls for descriptions (via `asyncio.gather`)
3. **Assembly** — `MechanicalStep`: render `TypeRegistry` → SDL string

Both branches run in parallel via `asyncio.gather` and produce independent outputs.

### Step classes (`cli/commands/analyze/steps/base.py`)

| Class | Behavior |
|---|---|
| `Step[In, Out]` | Base: calls `_execute()` then `_validate_output()` |
| `MechanicalStep` | No retry — validation failure is a bug |
| `LLMStep` | Retries on `StepValidationError` (max_retries=1), appends errors to conversation |

### LLM steps

| Step | File | Tools | Validation |
|---|---|---|---|
| Detect base URL | `steps/detect_base_url.py` | decode_base64, decode_url, decode_jwt | Valid URL (scheme + host) |
| Group endpoints (REST) | `steps/rest/group_endpoints.py` | decode_base64, decode_url, decode_jwt | Coverage, pattern match, no duplicates |
| Enrich endpoints (REST) | `steps/rest/enrich.py` | none | Best-effort (no validation) |
| Enrich types (GraphQL) | `steps/graphql/enrich.py` | none | Best-effort (no validation) |
| Auth analysis | `steps/analyze_auth.py` | none | Best-effort (fallback to `detect_auth_mechanical`) |

All LLM steps use `_extract_json()` to robustly parse LLM JSON responses (handles markdown blocks, nested objects).

### Internal data flow

Pipeline steps exchange typed dataclasses. Shared types live in `steps/types.py`, protocol-specific types in `steps/rest/types.py` and `steps/graphql/types.py`.

| Type | Location | Purpose |
|---|---|---|
| `MethodUrlPair` | `steps/types.py` | An observed (method, url) pair from a single trace |
| `AnalysisResult` | `steps/types.py` | Final output: optional `openapi` dict + optional `graphql_sdl` string |
| `AuthInfo` | `steps/types.py` | Detected auth type, obtain_flow, login/refresh config, user_journey |
| `EndpointGroup` | `steps/rest/types.py` | An LLM-identified REST endpoint group (method, pattern, urls) |
| `EndpointSpec` | `steps/rest/types.py` | Full REST endpoint with request/response schemas |
| `SpecComponents` | `steps/rest/types.py` | All pieces needed for the REST assembly step |
| `TypeRegistry` | `steps/graphql/types.py` | Accumulated GraphQL types, fields, enums from all traces |
| `GraphQLSchemaData` | `steps/graphql/types.py` | Final GraphQL schema with root fields + type registry |

---

## Implementation status

### Phase 1: Capture bundle format + Extension
- [x] Pydantic models for capture bundle format (`cli/formats/capture_bundle.py`) — 17 models including PageContent
- [x] Bundle loader/writer with ZIP serialization (`cli/commands/capture/loader.py`) — binary-safe roundtrip
- [x] In-memory data classes (`cli/commands/capture/types.py`) — wraps metadata + binary payloads
- [x] Chrome extension: modular background service worker (`background/`) — network, websocket, graphql, capture, export
- [x] Chrome extension: GraphQL interception via Fetch.requestPaused (`background/graphql.js`) — detection, APQ rejection, `__typename` injection
- [x] Chrome extension: content script (`content/content.js`) — DOM event capture, page content extraction, stable selector generation
- [x] Chrome extension: popup UI (`popup/`) — Start/Stop/Export buttons, live stats, status indicators
- [x] Tests: model roundtrips, bundle read/write, binary safety, lookups

### Phase 2: Analysis engine
- [x] Protocol detection (`cli/commands/analyze/protocol.py`) — REST, GraphQL, gRPC, binary, WS sub-protocols
- [x] Time-window correlation (`cli/commands/analyze/correlator.py`) — UI action → API calls with configurable window
- [x] Step-based pipeline (`cli/commands/analyze/pipeline.py`) — orchestrator with parallel REST + GraphQL branches
- [x] Step abstraction (`cli/commands/analyze/steps/base.py`) — Step[In,Out], LLMStep (retry), MechanicalStep
- [x] LLM base URL detection (`steps/detect_base_url.py`) — with investigation tools + call frequency hints
- [x] REST: LLM endpoint grouping (`steps/rest/group_endpoints.py`) — with investigation tools + validation
- [x] REST: LLM per-endpoint enrichment (`steps/rest/enrich.py`) — parallel per-endpoint calls via asyncio.gather
- [x] REST: Mechanical extraction (`steps/rest/extraction.py`) — schemas, params, trace matching
- [x] REST: OpenAPI 3.1 assembly (`steps/rest/assemble.py`) — security schemes, parameters, request bodies, responses
- [x] GraphQL: Query parsing (`steps/graphql/parser.py`) — operations, fragments, variables via graphql-core
- [x] GraphQL: Type extraction (`steps/graphql/extraction.py`) — TypeRegistry from queries + __typename responses
- [x] GraphQL: LLM per-type enrichment (`steps/graphql/enrich.py`) — parallel per-type calls via asyncio.gather
- [x] GraphQL: SDL assembly (`steps/graphql/assemble.py`) — render TypeRegistry → SDL string
- [x] GraphQL: __typename injection (`cli/commands/capture/graphql_utils.py`) — AST visitor via graphql-core
- [x] LLM auth analysis (`steps/analyze_auth.py`) — on all unfiltered traces, with mechanical fallback
- [x] JSON schema inference with format detection (`cli/commands/analyze/schemas.py`) — date, email, UUID, URI
- [x] Annotated schemas (`cli/commands/analyze/schemas.py`) — schema + observed values per property
- [x] Investigation tools (`cli/commands/analyze/tools.py`) — decode_base64, decode_url, decode_jwt, tool loop
- [x] Shared utilities (`cli/commands/analyze/utils.py`) — _pattern_to_regex, _compact_url, _sanitize_headers
- [x] Tests: pipeline, steps, schemas, tools, protocol, correlator, mechanical extraction, GraphQL full pipeline
- [ ] Real-world testing with actual API keys
- [ ] Prompt tuning for better enrichment quality

### Phase 3: Capture tools
- [x] MITM proxy engine (`cli/commands/capture/proxy.py`) — mitmproxy addons, flow conversion, bundle output
- [x] Bundle inspect command (`cli/commands/capture/inspect.py`) — summary + per-trace detail views
- [x] Domain discovery mode — log domains without intercepting
- [x] Android APK tools (`cli/commands/android/`) — list, pull, patch, install, cert
- [x] Tests: proxy engine, flow conversion, manifest compat, android

### Phase 4: Polish
- [x] Full CLI (`cli/main.py`) — commands: `analyze`, `capture`, `android`
- [x] Shared helpers (`cli/helpers/`) — naming, subprocess, http, console
- [ ] Bundle merging (combine multiple capture sessions for the same app)
- [ ] Privacy controls: exclude domains, redact headers/cookies

### Test coverage
377 tests across 25 test files in 8 subdirectories, all passing. Test structure mirrors `cli/commands/`:
- `tests/formats/` — Pydantic model roundtrips and defaults
- `tests/capture/` — Bundle loader, MITM proxy engine, GraphQL utils
- `tests/analyze/` — Protocol detection, correlator, pipeline, schemas, tools
- `tests/analyze/steps/` — Step base classes, detect base URL
- `tests/analyze/steps/rest/` — REST extraction, enrichment, assembly
- `tests/analyze/steps/graphql/` — GraphQL parser, extraction, enrichment, SDL assembly
- `tests/android/` — ADB, patch, android CLI (list, pull, patch, install, cert)
- `tests/cli/` — All CLI commands via Click test runner
- `tests/helpers/` — Naming, subprocess, HTTP, LLM helper

---

## Key technical notes

### Timestamp conversion in the extension
Chrome DevTools Protocol uses monotonic timestamps (seconds since browser start), not epoch time. `background/utils.js` converts these to epoch milliseconds by computing an offset: `Date.now() - (chromeTimestamp * 1000)` on the first event, then applying it consistently to all subsequent events.

### Binary handling in the extension
`Network.getResponseBody` returns `{ body: string, base64Encoded: boolean }`. When `base64Encoded` is true, decode to binary before writing to `.bin` file. When false, write as UTF-8 text. Always store as binary files to be uniform.

### WebSocket in the extension
Chrome DevTools Protocol gives us `Network.webSocketFrameSent` and `Network.webSocketFrameReceived` with `{ requestId, timestamp, response: { opcode, mask, payloadData } }`. The `payloadData` is a string for text frames and base64 for binary frames. Store both as `.bin` files with metadata in the companion `.json`.

### LLM-first analysis strategy (REST)
The REST pipeline is LLM-first (not mechanical-first with LLM enrichment):
1. The LLM identifies the business API base URL — filtering out CDN, analytics, trackers
2. The LLM groups URLs into endpoint patterns — this is more accurate than mechanical heuristics for complex APIs
3. For each group, mechanical extraction provides the raw data (schemas, params, headers)
4. N parallel per-endpoint LLM calls enrich each endpoint with focused business semantics
5. Per-step validation catches LLM mistakes (coverage, pattern mismatches) and retries once

Auth analysis runs in parallel with enrichment on ALL unfiltered traces (external auth providers would be filtered out by base URL detection). Both branches converge at assembly via `asyncio.gather`.

Per-endpoint enrichment trades a single large prompt for N small focused prompts. Each call reasons about one endpoint with full context, producing higher-quality enrichment. Failures are isolated — one endpoint failing doesn't affect others. All calls run concurrently via `asyncio.gather`.

### GraphQL request patterns

Both the Python protocol detector (`_is_graphql_item` in `protocol.py`) and the extension's interception filter (`isGraphQLItem` in `graphql.js`) recognize three shapes of GraphQL requests:

| Pattern | Shape | Query text available | Extension can inject `__typename` | Example |
|---|---|---|---|---|
| **Normal query** | `{"query": "query { ... }", ...}` | Yes | Yes | Most GraphQL clients |
| **Persisted query (hash)** | `{"extensions": {"persistedQuery": {...}}, ...}` | No (hash only) | Only if APQ rejection forces a retry with full query | Apollo APQ, Spotify |
| **Named operation** | `{"operation": "FetchUsers", "variables": {...}}` | No (name only) | No | Reddit |

The `operationName` key (standard GraphQL) is also accepted in place of `operation` for the named operation pattern. Both require a `variables` dict to distinguish from arbitrary JSON.

APQ rejection (returning `PersistedQueryNotFound`) works with standard Apollo clients that hold the full query as a fallback. It does not work with clients that only have the hash (Spotify) or only the operation name (Reddit) — these break with errors like "Fallback query not available". The popup exposes toggles for both `__typename` injection and APQ rejection so users can disable them per-site.

### GraphQL analysis strategy
The GraphQL pipeline is mechanical-first with LLM enrichment:
1. The extension injects `__typename` into all GraphQL queries at capture time (via `Fetch.requestPaused`), so responses carry type information
2. The extraction step parses queries via `graphql-core` and walks the parsed field tree alongside the JSON response data to reconstruct a `TypeRegistry` — object types, input types, enums, scalars, field nullability and list-ness
3. N parallel per-type LLM calls add descriptions to types and fields
4. The assembly step renders the `TypeRegistry` to SDL

This is different from REST because GraphQL's type system is explicit — `__typename` injection makes mechanical type reconstruction reliable without LLM involvement. The LLM only adds business descriptions.

For persisted/named queries where we cannot inject `__typename` or parse the query text, the pipeline can only infer types from response shapes (less precise — no field-level nullability or explicit type names).

### Path parameter inference
In the LLM-first pipeline, path parameters are inferred by the LLM during URL grouping. The LLM sees all observed URLs and identifies variable segments (IDs, UUIDs, hashes) to produce patterns like `/api/users/{user_id}/orders`.

The mechanical `_pattern_to_regex()` helper converts these patterns to regexes for validation: `{param}` → `[^/]+`.

### Schema inference (mechanical)
Given multiple JSON response bodies for the same endpoint, build annotated schemas (`cli/commands/analyze/schemas.py`):
- Union of all keys seen across samples
- For each key: infer type from values (string, number, boolean, array, object)
- Mark keys as optional if not present in all responses
- Detect common formats: ISO dates, emails, UUIDs, URLs
- Annotated schemas add up to 5 `observed` values per property for LLM context

---

## Dependencies

### Extension
- JSZip (bundled in `extension/lib/`) — ZIP file creation for bundle export

### CLI
```
click          # CLI framework
pydantic       # Data models and validation
anthropic      # Anthropic API client for LLM calls
graphql-core   # GraphQL query parsing and AST manipulation
pyyaml         # YAML output for OpenAPI
rich           # Pretty terminal output
python-dotenv  # .env file loading
requests       # HTTP requests
mitmproxy      # MITM proxy for capture
```

### Dev
```
pytest         # Test framework
pytest-cov     # Coverage reporting
pytest-asyncio # Async test support (asyncio_mode = "auto")
pyright        # Type checking
ruff           # Linting (isort)
```

## Environment variables

```
ANTHROPIC_API_KEY=sk-ant-...    # Required for analyze command
```
