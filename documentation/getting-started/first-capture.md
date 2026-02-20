# First capture

This guide walks you through capturing traffic from a web application using the Chrome extension.

## Start a capture

1. Navigate to the web application you want to analyze in Chrome
2. Click the Spectral extension icon in the toolbar to open the popup
3. Click **Start Capture**

The extension attaches a debugger to the active tab and begins recording all network traffic and UI interactions. The popup shows live statistics: HTTP request count, WebSocket connections and messages, UI event count, and elapsed time.

## Browse the application

Use the application as you normally would. Click through the main workflows you want to document — navigation, forms, data views, settings. The extension records:

- Every HTTP request and response (headers, bodies, timing)
- WebSocket connections and messages
- UI interactions: clicks, form inputs (values are not captured for privacy), form submissions, and page navigations
- Rich page context with each interaction: visible headings, navigation links, form fields, table headers, and alerts

The more workflows you exercise, the more complete the resulting API spec will be. Focus on the features that matter to your use case.

## GraphQL interception

If the application uses GraphQL, the extension can automatically inject `__typename` fields into queries. This makes type reconstruction more accurate during analysis. Two toggles are available in the popup:

| Toggle | Default | Purpose |
|--------|---------|---------|
| Inject `__typename` | On | Adds `__typename` to all selection sets so responses carry type information |
| Block persisted queries | On | Rejects Apollo APQ hashes to force clients to send full query text |

!!! warning
    Blocking persisted queries may break applications that do not hold the full query as a fallback (notably Spotify and Reddit). Disable this toggle if the app stops working after starting capture.

## Stop and export

1. Click **Stop Capture** in the popup. The extension detaches the debugger.
2. Click **Export Bundle**. The extension assembles a ZIP file and triggers a download.

The bundle file is named `capture_<timestamp>.zip` and contains all recorded data in Spectral's custom format. This is the input for the analysis step.

## Next steps

Take the exported bundle to [First analysis](first-analysis.md) to generate an API spec.
