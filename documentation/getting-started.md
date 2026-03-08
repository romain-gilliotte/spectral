# Getting started

## Install

```bash
curl -LsSf https://raw.githubusercontent.com/romain-gilliotte/spectral/main/install.sh | bash
```

This installs [uv](https://docs.astral.sh/uv/) if needed, then installs Spectral in an isolated environment with `spectral` available in `~/.local/bin/`.

## Load the Chrome extension

1. Open `chrome://extensions`, enable **Developer mode**, click **Load unpacked** and select the `extension/` directory from the repository
2. Copy the extension ID shown on the card
3. Connect the extension to the CLI:

```bash
spectral extension install --extension-id <paste-id-here>
```

## Capture traffic

1. Navigate to the web app you want to reverse-engineer
2. Click the Spectral extension icon → **Start Capture**
3. Browse the application — exercise the workflows you care about
4. Click **Stop & Send** — the capture is sent to the CLI via native messaging and stored automatically

You can repeat this for multiple sessions; captures are merged during analysis.

## Analyze

Generate MCP tools from the captured traffic:

```bash
spectral mcp analyze myapp
```

If the app requires authentication, generate a login script and authenticate:

```bash
spectral auth analyze myapp
spectral auth login myapp
```

## Use in Claude

Install the MCP server into Claude Desktop and/or Claude Code:

```bash
spectral mcp install
```

This auto-detects installed clients and registers the server. Use `--target claude-desktop` or `--target claude-code` to install to a specific client only. See [MCP tools](generation/mcp-tools.md) for details.

The server exposes all discovered API endpoints as tools. Authentication is handled automatically using stored tokens.

## Next steps

- [Capture — Web](capture/web.md) for the full capture reference (GraphQL interception, what gets captured, SPA handling)
- [Capture — Desktop](capture/desktop.md) and [Mobile](capture/mobile.md) for non-browser traffic
- [Authentication](authentication/index.md) for all auth options (generated scripts, manual tokens, direct extraction)
- [CLI reference](reference/cli.md) for the complete command list
