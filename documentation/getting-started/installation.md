# Installation

## Prerequisites

Spectral requires Python 3.11 or later and [uv](https://docs.astral.sh/uv/) as the package manager. You also need an [Anthropic API key](https://console.anthropic.com/) for the analysis step.

## Setup

Clone the repository and install dependencies:

```bash
git clone https://github.com/romain-gilliotte/spectral.git && cd spectral
uv sync
```

Create a `.env` file at the project root with your Anthropic API key:

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

The CLI loads this file automatically via `python-dotenv`. The key is only needed for the `analyze` command — capture works without it.

## Chrome extension

To capture web traffic, load the Chrome extension:

1. Open `chrome://extensions` in Chrome
2. Enable "Developer mode" (top right toggle)
3. Click "Load unpacked" and select the `extension/` directory from the repository

The extension icon should appear in your toolbar. See [Chrome extension](../capture/chrome-extension.md) for detailed usage.

## Verify the installation

Run the CLI to confirm everything is working:

```bash
uv run spectral --version
```

This should print `spectral, version 0.1.0`.

## Optional: Android tools

If you plan to capture traffic from Android apps, you also need:

- **adb** (Android SDK Platform Tools) — for communicating with the device
- **java** — for APK signing during patching

See [Android apps](../capture/android.md) for the full setup.
