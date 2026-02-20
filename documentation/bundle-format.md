# Bundle format

This page documents the capture bundle format for contributors and advanced users who want to understand or manipulate bundles directly.

## Overview

A capture bundle is a ZIP file containing network traces, WebSocket data, UI context events, and a timeline that ties everything together. The format was designed specifically for Spectral because existing formats like HAR have significant limitations:

- HAR is JSON/UTF-8 only — no native binary support (would need base64 encoding, adding 33% overhead)
- HAR has no standard WebSocket support (Chrome uses non-standard `_webSocketMessages`)
- HAR has no concept of UI context or unique trace IDs for cross-referencing
- HAR's request/response pair model doesn't fit WebSocket's async full-duplex messaging

## Bundle structure

| Path | Contents |
|------|----------|
| `manifest.json` | Session metadata: capture ID, timestamps, app info, browser info, statistics |
| `traces/t_NNNN.json` | HTTP trace metadata: method, URL, headers, status, timing, initiator, context refs |
| `traces/t_NNNN_request.bin` | Raw request body (binary-safe, may be empty) |
| `traces/t_NNNN_response.bin` | Raw response body (binary-safe, may be empty) |
| `ws/ws_NNNN.json` | WebSocket connection metadata: URL, handshake ref, protocols, message count |
| `ws/ws_NNNN_mNNN.bin` | WebSocket message payload (binary-safe) |
| `ws/ws_NNNN_mNNN.json` | WebSocket message metadata: direction, opcode, timestamp, connection ref |
| `contexts/c_NNNN.json` | UI context event: action type, element info, page URL, page content snapshot |
| `timeline.json` | Ordered list of all events with timestamps and cross-references |

## Manifest

The manifest contains session-level metadata:

| Field | Type | Description |
|-------|------|-------------|
| `format_version` | string | Bundle format version (currently `1.0.0`) |
| `capture_id` | string | Unique session identifier (UUID) |
| `created_at` | string | ISO 8601 timestamp |
| `app.name` | string | Application name |
| `app.base_url` | string | Application base URL |
| `app.title` | string | Page title at capture start |
| `browser.name` | string | Browser name |
| `browser.version` | string | Browser version |
| `extension_version` | string | Extension version |
| `duration_ms` | integer | Capture duration in milliseconds |
| `stats` | object | Counts: trace_count, ws_connection_count, ws_message_count, context_count |

## Trace metadata

Each trace has a stable string ID (`t_NNNN`) used for cross-referencing from contexts, timeline, and analysis output.

| Field | Description |
|-------|-------------|
| `id` | Trace identifier |
| `timestamp` | Epoch milliseconds |
| `type` | Always `http` |
| `request.method` | HTTP method |
| `request.url` | Full URL |
| `request.headers` | Array of `{name, value}` objects (arrays, not objects, because HTTP allows duplicate header names) |
| `request.body_file` | Path to the companion `.bin` file |
| `request.body_size` | Body size in bytes |
| `response.status` | HTTP status code |
| `response.headers` | Array of `{name, value}` objects |
| `response.body_file` | Path to the companion `.bin` file |
| `response.body_size` | Body size in bytes |
| `timing` | Breakdown: dns_ms, connect_ms, tls_ms, send_ms, wait_ms, receive_ms, total_ms |
| `initiator` | What triggered the request: type (script, parser, etc.), URL, line number |
| `context_refs` | Array of context IDs active when this trace was captured |

Bodies are stored as separate binary files rather than inline JSON to avoid encoding overhead and preserve binary fidelity.

## WebSocket data

WebSocket connections have a metadata file with the connection URL, handshake trace reference, negotiated protocols, and message count. Each message has its own metadata file (direction, opcode, timestamp) and a binary payload file.

| Opcode values | Meaning |
|---------------|---------|
| `text` | Text frame (UTF-8) |
| `binary` | Binary frame |
| `ping` | Ping control frame |
| `pong` | Pong control frame |
| `close` | Connection close frame |

Direction is `send` (client to server) or `receive` (server to client).

## UI context events

Each context event captures what the user did and the state of the page at that moment.

| Action | What is recorded |
|--------|-----------------|
| `click` | Element details (tag, text, attributes, CSS selector, XPath), page URL, page content |
| `input` | Field identity only (not the typed value, for privacy) |
| `submit` | Form target element |
| `navigate` | New URL (SPA navigation via pushState/replaceState/popstate) |

The page content snapshot includes visible headings (up to 10), navigation links (up to 15), main text content (up to 500 characters), forms with field identifiers (up to 5), table headers (up to 5), and alerts/notifications (up to 5).

## Timeline

The timeline is a flat ordered list of all events across traces, WebSocket activity, and context events. Each entry has a timestamp, an event type, and a reference to the corresponding item.

| Event type | Reference |
|------------|-----------|
| `context` | Context ID (e.g., `c_0001`) |
| `trace` | Trace ID (e.g., `t_0001`) |
| `ws_open` | WebSocket connection ID (e.g., `ws_0001`) |
| `ws_message` | WebSocket message ID (e.g., `ws_0001_m001`) |

The flat timeline makes correlation straightforward: to find which API calls relate to a UI action, scan forward from the context event within a time window.

## Timestamps

The Chrome extension converts Chrome DevTools Protocol timestamps (monotonic seconds since browser start) to epoch milliseconds. An offset is computed from the first event (`Date.now() - chromeTimestamp * 1000`) and applied consistently to all subsequent events. The MITM proxy uses wall-clock timestamps directly.
