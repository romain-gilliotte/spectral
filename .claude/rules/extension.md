---
paths:
  - "extension/**/*"
---

# Chrome Extension

## Capture flow

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
8. User clicks "Send to Spectral" → background sends the capture via Chrome Native Messaging to the CLI host

## State machine

`IDLE` → `ATTACHING` → `CAPTURING` → `SENDING` → `IDLE`

The popup polls the background for current state and stats, updating the UI accordingly:
- **idle**: Show "Start Capture" button
- **capturing**: Show live stats (requests, WS messages, UI events, duration) + "Stop Capture" button
- **stopped**: Show final stats + "Send to Spectral" button

## What we capture via DevTools Protocol

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

## What we capture via content script

| DOM event | What we record |
|---|---|
| `click` | Element selector, tag, text content, attributes, page URL, page content |
| `input` | Field identity (name, id, selector) — NOT the value (privacy), debounced 300ms |
| `submit` | Form target element |
| `pushState` / `replaceState` / `popstate` | Navigation URL changes (SPA) |

The content script also captures **rich page content** with each context event: visible headings (h1-h3), navigation links, main text content, form field identifiers and submit labels, table headers, alerts/notifications.

## Selector generation strategy

The content script generates stable CSS selectors using a priority chain:
1. Stable `id` attributes (filters out framework-generated IDs like `ember123`, `react-...`)
2. `data-testid` / `data-test` / `data-cy` attributes
3. Tag + `name` attribute for form elements
4. Fallback: tag + stable classes (filters framework CSS classes) + nth-child, up to 5 levels

## Context-to-trace correlation

When storing a trace, the extension finds the most recent context(s) within a 2-second lookback window and writes their IDs into `context_refs`. This is a rough first-pass correlation — the CLI's analyze step refines it with LLM reasoning.

## Technical notes

### Timestamp conversion
Chrome DevTools Protocol uses monotonic timestamps (seconds since browser start), not epoch time. `background/utils.js` converts these to epoch milliseconds by computing an offset: `Date.now() - (chromeTimestamp * 1000)` on the first event, then applying it consistently to all subsequent events.

### Binary handling
`Network.getResponseBody` returns `{ body: string, base64Encoded: boolean }`. When `base64Encoded` is true, decode to binary before writing to `.bin` file. When false, write as UTF-8 text. Always store as binary files to be uniform.

### WebSocket
Chrome DevTools Protocol gives us `Network.webSocketFrameSent` and `Network.webSocketFrameReceived` with `{ requestId, timestamp, response: { opcode, mask, payloadData } }`. The `payloadData` is a string for text frames and base64 for binary frames. Store both as `.bin` files with metadata in the companion `.json`.

### GraphQL request patterns

Both the Python protocol detector (`_is_graphql_item` in `protocol.py`) and the extension's interception filter (`isGraphQLItem` in `graphql.js`) recognize three shapes of GraphQL requests:

| Pattern | Shape | Query text available | Extension can inject `__typename` | Example |
|---|---|---|---|---|
| **Normal query** | `{"query": "query { ... }", ...}` | Yes | Yes | Most GraphQL clients |
| **Persisted query (hash)** | `{"extensions": {"persistedQuery": {...}}, ...}` | No (hash only) | Only if APQ rejection forces a retry with full query | Apollo APQ, Spotify |
| **Named operation** | `{"operation": "FetchUsers", "variables": {...}}` | No (name only) | No | Reddit |

The `operationName` key (standard GraphQL) is also accepted in place of `operation` for the named operation pattern. Both require a `variables` dict to distinguish from arbitrary JSON.

APQ rejection (returning `PersistedQueryNotFound`) works with standard Apollo clients that hold the full query as a fallback. It does not work with clients that only have the hash (Spotify) or only the operation name (Reddit). The popup exposes toggles for both `__typename` injection and APQ rejection so users can disable them per-site.
