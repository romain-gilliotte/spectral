# Installation

## Quick install

The install script downloads [uv](https://docs.astral.sh/uv/) (if not already present), installs Spectral in an isolated environment, and symlinks the `spectral` command into `~/.local/bin/`:

```bash
curl -LsSf https://raw.githubusercontent.com/romain-gilliotte/spectral/main/install.sh | bash
```

If you already have uv, you can skip the script and run:

```bash
uv tool install git+https://github.com/romain-gilliotte/spectral.git
```

## Update

Re-run the install script — it detects the existing installation and pulls the latest version:

```bash
curl -LsSf https://raw.githubusercontent.com/romain-gilliotte/spectral/main/install.sh | bash
```

Or manually:

```bash
uv tool install git+https://github.com/romain-gilliotte/spectral.git --reinstall
```

Managed storage (captures, tokens, API key) is preserved across updates.

## Windows

There is no install script for Windows yet. Run these two commands manually:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv tool install git+https://github.com/romain-gilliotte/spectral.git
```

## Development setup

Contributors who want to modify Spectral should clone the repository instead:

```bash
git clone https://github.com/romain-gilliotte/spectral.git && cd spectral
uv sync
```

When running from a local checkout, prefix commands with `uv run` (e.g. `uv run spectral mcp analyze myapp`).

## Anthropic API key

The first time you run an `analyze` command, Spectral will prompt for your Anthropic API key and save it to managed storage (`~/.local/share/spectral/api_key`). You can also set the `ANTHROPIC_API_KEY` environment variable to override the stored key. The key is only needed for the `analyze` commands — capture works without it.

## Chrome extension

To capture web traffic, load the Chrome extension:

1. Open `chrome://extensions` in Chrome
2. Enable "Developer mode" (top right toggle)
3. Click "Load unpacked" and select the `extension/` directory from the repository
4. Copy the extension ID shown on the card
5. Connect the extension to the CLI by installing the native messaging host:

```bash
spectral extension install --extension-id <paste-id-here>
```

The extension icon should appear in your toolbar. See [Chrome extension](../capture/chrome-extension.md) for detailed usage.

## Verify the installation

Run the CLI to confirm everything is working:

```bash
spectral --version
```

This should print `spectral, version 0.1.0`.

## Shell completion

Spectral supports tab-completion for commands, options, and app names in bash and zsh. Add one of the following lines to your shell profile:

- **bash** (`~/.bashrc`): `eval "$(spectral completion bash)"`
- **zsh** (`~/.zshrc`): `eval "$(spectral completion zsh)"`

Restart your shell or source the profile to activate completion.

## Uninstall

Remove the tool and its isolated environment:

```bash
uv tool uninstall spectral
```

If the install script added shell completion to your profile, remove the `eval "$(spectral completion ...)"` line from `~/.bashrc` or `~/.zshrc`.

To also remove managed storage (captures, tokens, API key), delete `~/.local/share/spectral/`.

## Optional: Android tools

If you plan to capture traffic from Android apps, you also need:

- **adb** (Android SDK Platform Tools) — for communicating with the device
- **java** — for APK signing during patching

See [Android apps](../capture/android.md) for the full setup.
