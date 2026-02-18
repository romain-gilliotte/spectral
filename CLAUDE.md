# api-discover — Project Specification

## Style preferences

- **No code samples in documentation.** Documentation files (`_documentation/`) should describe concepts in prose and tables, not paste code. The code lives in the code.

## Development environment

- Package manager is **uv**. Use `uv run` to execute commands (no need to activate the venv):
  - `uv run pytest tests/` — run tests
  - `uv run api-discover analyze ...` — run the CLI
  - `uv add <package>` — add a dependency (updates `pyproject.toml` + `uv.lock`)
  - `uv add --dev <package>` — add a dev dependency
- `.env` file at project root holds `ANTHROPIC_API_KEY` (loaded by the CLI via `python-dotenv`). Do NOT commit `.env`.

## What this project is

A three-stage pipeline that automatically discovers and documents web application APIs:

1. **Capture** — A Chrome Extension passively records network traffic + UI actions while the user browses normally
2. **Analyze** — A CLI tool correlates UI actions ↔ API calls using an LLM to produce a semantically-rich API spec
3. **Generate** — The CLI generates tooling from that spec: OpenAPI, MCP servers, Python clients, docs, etc.

The key innovation is the **correlation of UI actions with network traffic** to understand the *business meaning* of each API call, not just its technical shape. No existing tool does this.

## Project structure

```
api-discover/
├── extension/              # Chrome Extension (Manifest V3)
│   ├── manifest.json
│   ├── background.js       # Network capture via chrome.debugger (DevTools Protocol)
│   ├── content.js          # UI context capture (clicks, navigation, DOM state, page content)
│   ├── popup.html          # Start/stop/export UI with live stats
│   ├── popup.js            # Popup controller (state management, polling)
│   ├── popup.css           # Popup styling (320px popup, status indicators)
│   ├── lib/
│   │   └── jszip.min.js    # ZIP library for bundle export
│   └── icons/
│       ├── icon16.png
│       ├── icon48.png
│       └── icon128.png
├── cli/                    # Python CLI tool
│   ├── __init__.py
│   ├── main.py             # Entry point: commands (analyze, generate, capture, call, android)
│   ├── capture/            # Capture: bundle parsing, inspect, MITM proxy
│   │   ├── cmd.py          # CLI group: capture inspect, capture proxy
│   │   ├── proxy.py        # Generic MITM proxy engine (mitmproxy addons, run_proxy)
│   │   ├── loader.py       # Unzips and loads a capture bundle (+ write_bundle)
│   │   └── types.py        # Data classes for traces, contexts, timeline (wraps Pydantic + binary)
│   ├── analyze/            # Analysis engine
│   │   ├── pipeline.py     # Orchestrator: build_spec() with parallel branches
│   │   ├── correlator.py   # Time-window correlation: UI action → API calls
│   │   ├── protocol.py     # Protocol detection (REST, GraphQL, WebSocket, gRPC, binary)
│   │   ├── tools.py        # LLM tool loop (_call_with_tools), investigation tools, _extract_json
│   │   ├── utils.py        # Shared utilities (_pattern_to_regex, _compact_url, _sanitize_headers)
│   │   ├── schemas.py      # JSON schema inference, annotated schemas, format detection
│   │   └── steps/          # Pipeline steps (Step[In,Out] architecture)
│   │       ├── types.py            # Intermediate dataclasses (Correlation, EndpointGroup, etc.)
│   │       ├── base.py             # Step, LLMStep, MechanicalStep, StepValidationError
│   │       ├── detect_base_url.py  # LLMStep: identify business API base URL
│   │       ├── group_endpoints.py  # LLMStep: group URLs into endpoint patterns
│   │       ├── analyze_auth.py     # LLMStep: detect auth mechanism from all traces
│   │       ├── enrich_and_context.py # LLMStep: batch enrichment + business context
│   │       ├── extract_pairs.py    # MechanicalStep: traces → (method, url) pairs
│   │       ├── filter_traces.py    # MechanicalStep: keep traces matching base URL
│   │       ├── strip_prefix.py     # MechanicalStep: remove base URL path prefix
│   │       ├── mechanical_extraction.py # MechanicalStep: groups → EndpointSpec[]
│   │       ├── build_ws_specs.py   # MechanicalStep: WS connections → WS protocol
│   │       └── assemble.py         # MechanicalStep: combine all parts → ApiSpec
│   ├── generate/           # Output generators
│   │   ├── openapi.py      # Enriched OpenAPI 3.1 output
│   │   ├── mcp_server.py   # MCP server scaffold generation (FastMCP)
│   │   ├── python_client.py# Python SDK with business-named methods
│   │   ├── markdown_docs.py# Human-readable documentation (index + per-endpoint + auth)
│   │   └── curl_scripts.py # Ready-to-use cURL examples (per-endpoint + all-in-one)
│   └── formats/            # Shared format definitions
│       ├── capture_bundle.py   # Capture bundle Pydantic models (17 models)
│       └── api_spec.py         # Enriched API spec Pydantic models
├── tests/
│   ├── conftest.py         # Shared fixtures (sample_bundle, make_trace, make_context, etc.)
│   ├── test_formats.py
│   ├── test_loader.py
│   ├── test_protocol.py
│   ├── test_correlator.py
│   ├── test_spec_builder.py # Pipeline, mechanical extraction, schema inference
│   ├── test_schemas.py      # Annotated schemas, type inference, format detection
│   ├── test_steps.py        # Step base classes (Step, LLMStep, MechanicalStep)
│   ├── test_llm_tools.py    # Tool executors, _call_with_tools, DetectBaseUrlStep
│   ├── test_generators.py
│   ├── test_client.py
│   ├── test_cli.py
│   ├── test_android.py      # ADB, patch, android CLI (list, pull, patch, install, cert)
│   └── test_capture_proxy.py # MITM proxy engine, flow conversion, manifest compat
├── pyproject.toml
└── README.md
```

## Data model convention

| Pattern | Contents | Python construct |
|---------|----------|-----------------|
| `formats/<name>.py` | Serialization models (external formats: capture bundle, API spec) | Pydantic `BaseModel` |
| `<package>/types.py` | Internal types passed between modules | `@dataclass` |

## Technology choices

- **Extension**: Vanilla JS, Chrome Manifest V3, Chrome DevTools Protocol (via `chrome.debugger`), JSZip for bundle export
- **CLI**: Python 3.11+, Click for CLI, Pydantic for data models
- **LLM**: Anthropic API (Claude Sonnet) for semantic analysis
- **Packaging**: pyproject.toml with `[project.scripts]` entry point for `api-discover`

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

## FORMAT 2: Enriched API Specification (.json)

This is the output of `api-discover analyze`. It's what makes the project unique: a spec that contains not just technical API shape, but business meaning, user stories, and workflow context inferred by the LLM.

```json
{
  "api_spec_version": "1.0.0",
  "name": "EDF Customer Portal API",
  "discovery_date": "2026-02-13T15:30:00Z",
  "source_captures": ["capture_20260213_153000.zip"],

  "business_context": {
    "domain": "Energy Management",
    "description": "Customer-facing API for the EDF energy provider portal",
    "user_personas": ["residential_customer", "business_customer"],
    "key_workflows": [
      {
        "name": "view_consumption",
        "description": "Customer views their monthly electricity consumption",
        "steps": ["login", "navigate_to_dashboard", "select_consumption_tab", "view_data"]
      }
    ]
  },

  "auth": {
    "type": "bearer_token",
    "obtain_flow": "oauth2_authorization_code",
    "business_process": "Two-factor authentication with SMS verification",
    "user_journey": [
      "Enter email/password on login page",
      "Receive SMS verification code",
      "Enter SMS code",
      "Access granted — token valid ~24h"
    ],
    "token_header": "Authorization",
    "token_prefix": "Bearer",
    "refresh_endpoint": "/api/auth/refresh",
    "discovery_notes": "Token appears in all subsequent requests. 401 triggers redirect to /login."
  },

  "protocols": {
    "rest": {
      "base_url": "https://api.edf.fr",
      "endpoints": [
        {
          "id": "get_monthly_consumption",
          "path": "/api/consumption/monthly",
          "method": "POST",
          "business_purpose": "Retrieve customer's monthly electricity consumption data",
          "user_story": "As a customer, I want to view my monthly energy usage to understand my consumption patterns",
          "ui_triggers": [
            {
              "action": "click",
              "element_selector": "nav[data-tab='consumption']",
              "element_text": "Ma consommation",
              "page_url": "/dashboard",
              "user_explanation": "User clicks on 'Ma consommation' tab in main navigation"
            }
          ],
          "request": {
            "content_type": "application/json",
            "parameters": [
              {
                "name": "period",
                "location": "body",
                "type": "string",
                "format": "YYYY-MM",
                "required": true,
                "business_meaning": "Billing period for consumption lookup",
                "example": "2024-01",
                "constraints": "Cannot be future date, max 24 months history",
                "observed_values": ["2024-01", "2024-02", "2024-03"]
              }
            ]
          },
          "responses": [
            {
              "status": 200,
              "content_type": "application/json",
              "business_meaning": "Successfully retrieved consumption data",
              "example_scenario": "Customer viewing January 2024 consumption",
              "schema": {
                "type": "object",
                "properties": {
                  "period": { "type": "string" },
                  "consumption_kwh": { "type": "number" },
                  "cost_euros": { "type": "number" },
                  "comparison_previous_year": { "type": "number" }
                }
              },
              "example_body": { "period": "2024-01", "consumption_kwh": 342.5, "cost_euros": 58.20, "comparison_previous_year": -12.3 }
            },
            {
              "status": 403,
              "business_meaning": "Customer contract expired or suspended",
              "user_impact": "Cannot view consumption data",
              "resolution": "Contact customer service to reactivate account"
            }
          ],
          "rate_limit": null,
          "requires_auth": true,
          "correlation_confidence": 0.95,
          "discovery_notes": "Always called after successful authentication, requires active contract",
          "observed_count": 5,
          "source_trace_refs": ["t_0001", "t_0023", "t_0045", "t_0067", "t_0078"]
        }
      ]
    },
    "websocket": {
      "connections": [
        {
          "id": "realtime_updates",
          "url": "wss://realtime.edf.fr/socket",
          "subprotocol": "graphql-ws",
          "business_purpose": "Real-time consumption data streaming",
          "messages": [
            {
              "direction": "send",
              "label": "subscribe_consumption",
              "business_purpose": "Subscribe to live consumption updates",
              "payload_schema": { "type": "object", "properties": { "type": { "const": "subscribe" }, "id": { "type": "string" } } },
              "example_payload": { "type": "subscribe", "id": "1", "payload": { "query": "subscription { consumption { kwh } }" } }
            }
          ]
        }
      ]
    }
  },

  "business_glossary": {
    "consumption": "kWh energy usage measured by smart meter",
    "billing_period": "Monthly cycles from 1st to last day of month",
    "contract": "Legal agreement between EDF and customer for energy supply",
    "PDL": "Point de Livraison — unique identifier for a delivery point (meter)"
  }
}
```

### What the LLM infers (Stage 2 — analyze)

The LLM is called during `api-discover analyze` to produce these fields that a purely mechanical tool could not:

- `business_purpose` — what the endpoint does in business terms
- `user_story` — "As a [persona], I want to [action] so that [goal]"
- `ui_triggers[].user_explanation` — natural language description of what the user did
- `parameters[].business_meaning` — what a parameter means in domain terms
- `parameters[].constraints` — inferred constraints from observed values
- `responses[].business_meaning` — what a response means
- `responses[].resolution` — how to fix an error, in user terms
- `business_glossary` — domain-specific terms extracted from UI text and API field names
- `business_context.key_workflows` — user workflows reconstructed from the timeline
- `auth.user_journey` — the authentication flow described for humans
- `correlation_confidence` — how confident the LLM is in the UI↔API correlation

Everything else is mechanical (headers, schemas, status codes, URLs, timing).

---

## CLI commands

```bash
# Stage 2: Analyze a capture bundle → enriched API spec (requires ANTHROPIC_API_KEY)
api-discover analyze capture_20260213.zip -o edf-api.json
api-discover analyze capture_20260213.zip -o edf-api.json --model claude-sonnet-4-5-20250929

# Stage 3: Generate outputs from enriched spec
api-discover generate edf-api.json --type openapi    -o edf-openapi.yaml
api-discover generate edf-api.json --type mcp-server -o edf-mcp-server/
api-discover generate edf-api.json --type python-client -o edf_client.py
api-discover generate edf-api.json --type markdown-docs -o docs/
api-discover generate edf-api.json --type curl-scripts  -o scripts/

# Capture: inspect bundles, run MITM proxy
spectral capture inspect capture_20260213.zip                    # summary stats
spectral capture inspect capture_20260213.zip --trace t_0001     # details of one trace
spectral capture proxy -d "api\.example\.com" -o capture.zip     # MITM proxy capture
spectral capture proxy                                           # discovery mode (log domains)

# Android: APK tools
spectral android list spotify
spectral android pull com.spotify.music
spectral android patch com.spotify.music.apk
spectral android install com.spotify.music-patched.apk
spectral android cert                                            # push mitmproxy CA cert to device
```

Note: `analyze` requires LLM analysis (requires `ANTHROPIC_API_KEY`). Default model is `claude-sonnet-4-5-20250929`.

---

## Chrome Extension behavior

### Capture flow

1. User clicks "Start Capture" in extension popup
2. Extension attaches `chrome.debugger` to the active tab
3. `background.js` listens to DevTools Protocol events:
   - `Network.requestWillBeSent` — capture request metadata (provisional headers)
   - `Network.requestWillBeSentExtraInfo` — capture wire-level request headers (Cookie, browser-managed Auth)
   - `Network.responseReceived` + `Network.getResponseBody` — capture response metadata + body
   - `Network.responseReceivedExtraInfo` — capture wire-level response headers (Set-Cookie, cross-origin)
   - `Network.webSocketCreated`, `Network.webSocketFrameSent`, `Network.webSocketFrameReceived` — WebSocket
4. `content.js` listens to DOM events (click, input, submit) and navigation events, extracts rich page content
5. Content script sends timestamped context events to background.js via `chrome.runtime.sendMessage`
6. On full-page navigation (non-SPA), `chrome.tabs.onUpdated` re-injects `content.js` automatically so UI capture continues
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

The `build_spec()` function in `pipeline.py` orchestrates a Step-based pipeline with three parallel branches. Each step is a typed `Step[In, Out]` with `run()` method, optional validation, and retry for LLM steps. See `_documentation/00-overview.md` for the full pipeline diagram.

**Main branch** (sequential):
1. **Extract pairs** — `MechanicalStep`: collect `(method, url)` pairs from all traces
2. **Detect base URL** — `LLMStep`: identify the business API origin (with investigation tools)
3. **Filter traces** — `MechanicalStep`: keep only traces matching the base URL
4. **Group endpoints** — `LLMStep`: group URLs into endpoint patterns with `{param}` syntax (with investigation tools)
5. **Strip prefix** — `MechanicalStep`: remove base URL path prefix from patterns
6. **Mechanical extraction** — `MechanicalStep`: build `EndpointSpec[]` with schemas, params, UI triggers
7. **Enrich + context** — `LLMStep`: single batch call for ALL endpoint enrichments + business context + glossary

**Parallel branches** (run via `asyncio.gather` alongside step 7):
- **Auth analysis** — `LLMStep`: detect auth mechanism from ALL unfiltered traces (summary-based, no tools)
- **WebSocket specs** — `MechanicalStep`: extract WS protocol specs from captured connections

**Assembly** — `MechanicalStep`: combine all outputs into `ApiSpec`

### Step classes (`cli/analyze/steps/base.py`)

| Class | Behavior |
|---|---|
| `Step[In, Out]` | Base: calls `_execute()` then `_validate_output()` |
| `MechanicalStep` | No retry — validation failure is a bug |
| `LLMStep` | Retries on `StepValidationError` (max_retries=1), appends errors to conversation |

### LLM steps

| Step | File | Tools | Validation |
|---|---|---|---|
| Detect base URL | `detect_base_url.py` | decode_base64, decode_url, decode_jwt | Valid URL (scheme + host) |
| Group endpoints | `group_endpoints.py` | decode_base64, decode_url, decode_jwt | Coverage, pattern match, no duplicates |
| Enrich + context | `enrich_and_context.py` | none | Best-effort (no validation) |
| Auth analysis | `analyze_auth.py` | none | Best-effort (fallback to mechanical) |

All LLM steps use `_extract_json()` to robustly parse LLM JSON responses (handles markdown blocks, nested objects).

---

## Implementation status

### Phase 1: Capture bundle format + Extension
- [x] Pydantic models for capture bundle format (`cli/formats/capture_bundle.py`) — 17 models including PageContent
- [x] Bundle loader/writer with ZIP serialization (`cli/capture/loader.py`) — binary-safe roundtrip
- [x] In-memory data classes (`cli/capture/types.py`) — wraps metadata + binary payloads
- [x] Chrome extension: `background.js` — DevTools Protocol capture, state machine, timestamp conversion
- [x] Chrome extension: `content.js` — DOM event capture, page content extraction, stable selector generation
- [x] Chrome extension: popup UI — Start/Stop/Export buttons, live stats, status indicators
- [x] Tests: model roundtrips, bundle read/write, binary safety, lookups

### Phase 2: Analysis engine
- [x] Protocol detection (`cli/analyze/protocol.py`) — REST, GraphQL, gRPC, binary, WS sub-protocols
- [x] Time-window correlation (`cli/analyze/correlator.py`) — UI action → API calls with configurable window
- [x] Step-based pipeline (`cli/analyze/pipeline.py`) — orchestrator with parallel branches via asyncio.gather
- [x] Step abstraction (`cli/analyze/steps/base.py`) — Step[In,Out], LLMStep (retry), MechanicalStep
- [x] LLM base URL detection (`steps/detect_base_url.py`) — with investigation tools
- [x] LLM endpoint grouping (`steps/group_endpoints.py`) — with investigation tools + validation
- [x] LLM batch enrichment + business context (`steps/enrich_and_context.py`) — single call for all endpoints
- [x] LLM auth analysis (`steps/analyze_auth.py`) — on all unfiltered traces, with mechanical fallback
- [x] Mechanical extraction (`steps/mechanical_extraction.py`) — schemas, params, UI triggers, trace matching
- [x] JSON schema inference with format detection (`cli/analyze/schemas.py`) — date, email, UUID, URI
- [x] Annotated schemas (`cli/analyze/schemas.py`) — schema + observed values per property
- [x] Investigation tools (`cli/analyze/tools.py`) — decode_base64, decode_url, decode_jwt, tool loop
- [x] Shared utilities (`cli/analyze/utils.py`) — _pattern_to_regex, _compact_url, _sanitize_headers
- [x] Tests: pipeline, steps, schemas, tools, protocol, correlator, mechanical extraction
- [ ] Real-world testing with actual API keys
- [ ] Prompt tuning for better business_purpose / user_story quality

### Phase 4: Output generators
- [x] OpenAPI 3.1 generator (`cli/generate/openapi.py`) — paths, params, request bodies, security schemes, tags
- [x] Python client generator (`cli/generate/python_client.py`) — typed methods, auth, docstrings
- [x] Markdown docs generator (`cli/generate/markdown_docs.py`) — index + per-endpoint + auth docs
- [x] cURL scripts generator (`cli/generate/curl_scripts.py`) — per-endpoint + all-in-one script
- [x] MCP server generator (`cli/generate/mcp_server.py`) — FastMCP scaffold with tools, README, requirements
- [x] Tests: structure, content, file output for all 5 generators

### Phase 5: Polish
- [x] `api-discover inspect` command — summary + per-trace detail view
- [x] Full CLI (`cli/main.py`) — commands: `analyze`, `generate`, `inspect`, `call`
- [ ] Bundle merging (combine multiple capture sessions for the same app)
- [ ] Privacy controls: exclude domains, redact headers/cookies

### Test coverage
207 tests across 11 test files, all passing:
- `tests/test_formats.py` — Pydantic model roundtrips and defaults
- `tests/test_loader.py` — Bundle read/write, binary safety, lookups
- `tests/test_protocol.py` — Protocol detection for HTTP and WebSocket
- `tests/test_correlator.py` — Time-window correlation logic
- `tests/test_spec_builder.py` — Pipeline builds, mechanical extraction, schema inference, trace matching
- `tests/test_schemas.py` — Annotated schemas, type inference, format detection, schema merging
- `tests/test_steps.py` — Step base classes: execution, validation, retry logic
- `tests/test_llm_tools.py` — Tool executors, _call_with_tools loop, DetectBaseUrlStep
- `tests/test_generators.py` — All 5 generators (structure, content, file output)
- `tests/test_client.py` — ApiClient: init, auth, calls, login flow, path extraction
- `tests/test_cli.py` — All CLI commands via Click test runner

---

## Key technical notes

### Timestamp conversion in the extension
Chrome DevTools Protocol uses monotonic timestamps (seconds since browser start), not epoch time. `background.js` converts these to epoch milliseconds by computing an offset: `Date.now() - (chromeTimestamp * 1000)` on the first event, then applying it consistently to all subsequent events.

### Binary handling in the extension
`Network.getResponseBody` returns `{ body: string, base64Encoded: boolean }`. When `base64Encoded` is true, decode to binary before writing to `.bin` file. When false, write as UTF-8 text. Always store as binary files to be uniform.

### WebSocket in the extension
Chrome DevTools Protocol gives us `Network.webSocketFrameSent` and `Network.webSocketFrameReceived` with `{ requestId, timestamp, response: { opcode, mask, payloadData } }`. The `payloadData` is a string for text frames and base64 for binary frames. Store both as `.bin` files with metadata in the companion `.json`.

### LLM-first analysis strategy
The analysis pipeline is LLM-first (not mechanical-first with LLM enrichment):
1. The LLM identifies the business API base URL — filtering out CDN, analytics, trackers
2. The LLM groups URLs into endpoint patterns — this is more accurate than mechanical heuristics for complex APIs
3. For each group, mechanical extraction provides the raw data (schemas, params, headers)
4. A single batch LLM call enriches ALL endpoints with business semantics + infers business context + glossary
5. Per-step validation catches LLM mistakes (coverage, pattern mismatches) and retries once

Auth analysis runs in parallel on ALL unfiltered traces (external auth providers would be filtered out by base URL detection). Three branches converge at assembly via `asyncio.gather`.

This keeps token usage low (batch enrichment instead of N+1 calls) while leveraging the LLM's strength at pattern recognition and semantic inference.

### Path parameter inference
In the LLM-first pipeline, path parameters are inferred by the LLM during URL grouping. The LLM sees all observed URLs and identifies variable segments (IDs, UUIDs, hashes) to produce patterns like `/api/users/{user_id}/orders`.

The mechanical `_pattern_to_regex()` helper converts these patterns to regexes for validation: `{param}` → `[^/]+`.

### Schema inference (mechanical)
Given multiple JSON response bodies for the same endpoint, build annotated schemas (`cli/analyze/schemas.py`):
- Union of all keys seen across samples
- For each key: infer type from values (string, number, boolean, array, object)
- Mark keys as optional if not present in all responses
- Detect common formats: ISO dates, emails, UUIDs, URLs
- Annotated schemas add up to 5 `observed` values per property for LLM context

---

## Dependencies

### Extension
- JSZip (bundled in `extension/lib/jszip.min.js`) — ZIP file creation for bundle export

### CLI
```
click          # CLI framework
pydantic       # Data models and validation
anthropic      # Anthropic API client for LLM calls
pyyaml         # YAML output for OpenAPI
rich           # Pretty terminal output
```

### Dev
```
pytest         # Test framework
pytest-cov     # Coverage reporting
pytest-asyncio # Async test support (asyncio_mode = "auto")
```

## Environment variables

```
ANTHROPIC_API_KEY=sk-ant-...    # Required for analyze command
```
