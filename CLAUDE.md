# api-discover — Project Specification

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
│   ├── content.js          # UI context capture (clicks, navigation, DOM state)
│   ├── popup.html          # Simple start/stop/export UI
│   └── popup.js
├── cli/                    # Python CLI tool
│   ├── __init__.py
│   ├── main.py             # Entry point: `api-discover analyze` / `api-discover generate`
│   ├── capture/            # Stage 2: Capture bundle parsing
│   │   ├── loader.py       # Unzips and loads a capture bundle
│   │   └── models.py       # Data classes for traces, contexts, timeline
│   ├── analyze/            # Stage 2: Analysis engine
│   │   ├── correlator.py   # Time-window correlation: UI action → API calls
│   │   ├── protocol.py     # Protocol detection (REST, GraphQL, WebSocket, gRPC, binary)
│   │   ├── llm.py          # LLM client for semantic inference (Anthropic API)
│   │   └── spec_builder.py # Builds the enriched API spec from correlations
│   ├── generate/           # Stage 3: Output generators
│   │   ├── openapi.py      # Enriched OpenAPI 3.1 output
│   │   ├── mcp_server.py   # MCP server scaffold generation
│   │   ├── python_client.py# Python SDK with business-named methods
│   │   ├── markdown_docs.py# Human-readable documentation
│   │   └── curl_scripts.py # Ready-to-use cURL examples
│   └── formats/            # Shared format definitions
│       ├── capture_bundle.py   # Capture bundle schema & validation
│       └── api_spec.py         # Enriched API spec schema & validation
├── pyproject.toml
└── README.md
```

## Technology choices

- **Extension**: Vanilla JS, Chrome Manifest V3, Chrome DevTools Protocol (via `chrome.debugger`)
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

The bundle can still import/export HAR for compatibility with existing tooling.

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
│   ├── c_0001.json            # UI context snapshot
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
      "data-tab": "consumption",
      "class": "nav-item active"
    },
    "xpath": "/html/body/div[2]/nav/div[3]"
  },
  "page": {
    "url": "https://www.edf.fr/dashboard",
    "title": "Mon espace client - EDF"
  },
  "viewport": {
    "width": 1440,
    "height": 900,
    "scroll_x": 0,
    "scroll_y": 200
  }
}
```

Captured UI actions:
- `click` — user clicks an element
- `input` — user types in a field (value NOT captured by default for privacy — only field identity)
- `submit` — form submission
- `navigate` — page navigation (pushState, popstate, full navigation)
- `scroll` — significant scroll events (debounced)

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
# Stage 2: Analyze a capture bundle → enriched API spec
api-discover analyze capture_20260213.zip -o edf-api.json
api-discover analyze capture_20260213.zip -o edf-api.json --model claude-sonnet-4-5  # choose model
api-discover analyze capture_20260213.zip -o edf-api.json --no-llm                  # skip LLM, mechanical only

# Stage 3: Generate outputs from enriched spec
api-discover generate edf-api.json --type openapi    -o edf-openapi.yaml
api-discover generate edf-api.json --type mcp-server -o edf-mcp-server/
api-discover generate edf-api.json --type python-client -o edf_client.py
api-discover generate edf-api.json --type markdown-docs -o docs/
api-discover generate edf-api.json --type curl-scripts  -o scripts/

# Full pipeline
api-discover pipeline capture_20260213.zip --types openapi,mcp-server,python-client -o output/

# Utility: import/export HAR for compatibility
api-discover import-har recording.har -o capture.zip        # HAR → capture bundle
api-discover export-har capture.zip -o recording.har         # capture bundle → HAR (lossy: no UI context, binary→base64)

# Utility: inspect a capture bundle
api-discover inspect capture_20260213.zip                    # summary stats
api-discover inspect capture_20260213.zip --trace t_0001     # details of one trace
```

---

## Chrome Extension behavior

### Capture flow

1. User clicks "Start Capture" in extension popup
2. Extension attaches `chrome.debugger` to the active tab
3. `background.js` listens to DevTools Protocol events:
   - `Network.requestWillBeSent` — capture request metadata
   - `Network.responseReceived` + `Network.getResponseBody` — capture response metadata + body
   - `Network.webSocketCreated`, `Network.webSocketFrameSent`, `Network.webSocketFrameReceived` — WebSocket
4. `content.js` listens to DOM events (click, input, submit) and navigation events
5. Both sides send timestamped events to background.js which stores them in-memory
6. User clicks "Stop Capture" → background detaches debugger
7. User clicks "Export" → background assembles the ZIP bundle and triggers download

### What we capture via DevTools Protocol

| Protocol event | What we get |
|---|---|
| `Network.requestWillBeSent` | URL, method, headers, POST body, initiator, timestamp |
| `Network.responseReceived` | Status, headers, MIME type, timing |
| `Network.getResponseBody` | Full response body (text or base64-encoded binary) |
| `Network.webSocketCreated` | WebSocket URL |
| `Network.webSocketFrameSent` | Outgoing WS message (text or binary as base64) |
| `Network.webSocketFrameReceived` | Incoming WS message (text or binary as base64) |
| `Network.webSocketClosed` | WS connection closed |

### What we capture via content script

| DOM event | What we record |
|---|---|
| `click` | Element selector, tag, text content, attributes, page URL |
| `input` | Field identity (name, id, selector) — NOT the value (privacy) |
| `submit` | Form action, method, field identifiers |
| `popstate` / `pushState` interception | Navigation URL changes (SPA) |
| `beforeunload` | Full page navigations |

### Context↔Trace correlation (in extension)

When storing a trace, the extension finds the most recent context(s) within a 2-second lookback window and writes their IDs into `context_refs`. This is a rough first-pass correlation — the CLI's analyze step refines it with LLM reasoning.

---

## Implementation order

Build in this order. Each phase should be independently testable.

### Phase 1: Capture bundle format + Extension MVP
1. Define Pydantic models for the capture bundle format (cli/formats/capture_bundle.py)
2. Write a bundle loader that can read and validate a ZIP (cli/capture/loader.py)
3. Write a test that creates a sample bundle programmatically and loads it back
4. Build the Chrome extension: background.js with DevTools Protocol capture
5. Build the Chrome extension: content.js with DOM event capture
6. Build the popup UI: Start / Stop / Export buttons
7. Test: browse a simple site, export, load the bundle with the CLI loader

### Phase 2: Mechanical analysis (no LLM)
1. Protocol detection from trace metadata (content-type, URL patterns, WS handshake)
2. Time-window correlation: for each context, find traces within 2s
3. Group traces by endpoint (same method + URL path pattern)
4. Infer path parameters from URL variations (e.g., `/users/123` and `/users/456` → `/users/{id}`)
5. Infer request/response schemas from observed JSON bodies (merge across observations)
6. Build the enriched API spec with all mechanical fields filled in, LLM fields left as null
7. Test: load a real capture → produce a spec → validate it has sensible endpoints

### Phase 3: LLM analysis
1. Build the LLM client (Anthropic API, claude-sonnet)
2. For each correlated (context, traces) pair, ask the LLM to infer business_purpose, user_story, user_explanation
3. For each endpoint's parameters, ask the LLM to infer business_meaning and constraints
4. Ask the LLM to infer the overall business_context and business_glossary from all data
5. Ask the LLM to reconstruct auth flow from login-related traces
6. Fill in correlation_confidence scores
7. Test: compare LLM-enriched spec vs mechanical-only spec

### Phase 4: Output generators
1. OpenAPI 3.1 generator (most standard, test with swagger-ui)
2. Python client generator (business-named methods, type hints, error handling)
3. Markdown documentation generator
4. cURL scripts generator
5. MCP server generator (scaffold a working MCP server with tools for each endpoint)

### Phase 5: Polish
1. HAR import/export for compatibility
2. `api-discover inspect` command for debugging bundles
3. Bundle merging (combine multiple capture sessions for the same app)
4. Better popup UI with live capture stats
5. Privacy controls: exclude domains, redact headers/cookies

---

## Key technical notes

### Binary handling in the extension
`Network.getResponseBody` returns `{ body: string, base64Encoded: boolean }`. When `base64Encoded` is true, decode to binary before writing to `.bin` file. When false, write as UTF-8 text. Always store as binary files to be uniform.

### WebSocket in the extension
Chrome DevTools Protocol gives us `Network.webSocketFrameSent` and `Network.webSocketFrameReceived` with `{ requestId, timestamp, response: { opcode, mask, payloadData } }`. The `payloadData` is a string for text frames and base64 for binary frames. Store both as `.bin` files with metadata in the companion `.json`.

### LLM prompt strategy
Don't send the entire bundle to the LLM. Instead:
1. First, do ALL mechanical analysis (protocol detection, correlation, schema inference)
2. Then send focused prompts per endpoint: "Here is an API endpoint [URL, method, sample request/response] that was triggered by [UI action on element X on page Y]. What is the business purpose? Write a user story."
3. Then one final prompt with all discovered endpoints for the business glossary and workflow reconstruction

This keeps token usage low and prompts focused.

### Path parameter inference (mechanical)
Given these observed URLs:
```
/api/users/123/orders
/api/users/456/orders
/api/users/789/orders
```
Detect that segment 3 varies while others are constant → infer `/api/users/{user_id}/orders`.
Heuristic: if a URL segment is numeric or UUID-like and varies across traces for the same path structure, it's a parameter.

### Schema inference (mechanical)
Given multiple JSON response bodies for the same endpoint, merge them:
- Union of all keys seen
- For each key: infer type from values (string, number, boolean, array, object)
- Mark keys as optional if not present in all responses
- Detect common formats: ISO dates, emails, UUIDs, URLs

---

## Dependencies

### Extension
None — vanilla JS, Chrome APIs only.

### CLI
```
click          # CLI framework
pydantic       # Data models and validation
anthropic      # Anthropic API client for LLM calls
pyyaml         # YAML output for OpenAPI
rich           # Pretty terminal output
```

## Environment variables

```
ANTHROPIC_API_KEY=sk-ant-...    # Required for LLM analysis (not needed for --no-llm)
```
