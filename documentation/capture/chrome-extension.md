# Chrome extension

The Chrome extension captures network traffic and UI context from web applications using the Chrome DevTools Protocol.

## Installation

1. Open `chrome://extensions` in Chrome
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked** and select the `extension/` directory from the repository

The extension icon ("API Discover") appears in your toolbar.

## Capture flow

The popup UI guides you through three states:

| State | What you see | Action |
|-------|-------------|--------|
| Idle | "Ready to capture" | Click **Start Capture** |
| Capturing | Live stats (requests, WS, UI events, duration) | Browse the app, then click **Stop Capture** |
| Stopped | Final stats | Click **Export Bundle** to download the ZIP |

When you click Start Capture, the extension attaches a debugger to the active tab. Chrome shows a yellow "is debugging this tab" banner — this is expected. The debugger detaches automatically when you stop the capture.

## What gets captured

### Network traffic

The extension captures every HTTP request and response through the active tab, including:

- Full request: method, URL, headers (including cookies and authorization), body
- Full response: status code, headers (including set-cookie), body
- Timing breakdown: DNS, connect, TLS, send, wait, receive

Headers are captured at wire level, meaning browser-managed headers like `Cookie` and `Authorization` are included even if they were not set by the application's JavaScript.

### WebSocket

WebSocket connections are tracked from creation to close. Each frame (sent or received) is recorded with its payload and direction. Both text and binary frames are supported.

### UI context

A content script listens to DOM events and captures rich context with each interaction:

| Event | What is recorded |
|-------|-----------------|
| Click | Clicked element (tag, text, attributes, CSS selector, XPath), page URL, page content snapshot |
| Input | Field identity (name, id, selector) — the typed value is **not** captured for privacy. Debounced at 300ms. |
| Submit | Form target element |
| Navigate | New URL (pushState, replaceState, popstate for SPA navigation) |

Each context event also includes a page content snapshot: visible headings, navigation links, main text, form fields, table headers, and alerts. This rich context helps the LLM understand the business meaning of concurrent API calls.

### Selector generation

The extension generates stable CSS selectors for captured elements using a priority chain: stable `id` attributes (filtering out framework-generated IDs), then `data-testid`/`data-test`/`data-cy` attributes, then tag + name for form elements, then a fallback combining tag, stable classes, and nth-child up to 5 levels.

## GraphQL interception

The extension detects GraphQL requests and can modify them in flight to improve analysis quality.

### `__typename` injection

When enabled (default), the extension intercepts outgoing GraphQL requests via `Fetch.requestPaused` and adds `__typename` to every selection set. This makes responses carry explicit type information, which the analysis pipeline uses to reconstruct the GraphQL schema accurately.

### Persisted query blocking

When enabled (default), the extension rejects Apollo Automatic Persisted Queries (APQ) by returning a `PersistedQueryNotFound` error. Standard Apollo clients respond by resending the full query text, which the extension can then process normally.

!!! warning
    Some applications only have the persisted query hash and cannot fall back to the full query text. If the application breaks after starting capture, disable the "Block persisted queries" toggle in the popup and try again.

Both toggles are accessible in the popup UI during capture.

## SPA navigation

For single-page applications, the content script persists across in-page navigations. For full-page navigations, Chrome automatically re-injects the content script via the extension's manifest configuration, so UI capture continues seamlessly.

## Context-to-trace correlation

When a network trace is recorded, the extension links it to the most recent UI context events within a 2-second lookback window by writing their IDs into the trace's `context_refs` field. This rough first-pass correlation is refined by the LLM during analysis.
