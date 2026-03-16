#!/usr/bin/env bash
set -euo pipefail

# Colors
bold='\033[1m'
green='\033[0;32m'
yellow='\033[0;33m'
cyan='\033[0;36m'
reset='\033[0m'

info()  { echo -e "${cyan}${bold}==>${reset}${bold} $1${reset}"; }
ok()    { echo -e "${green}${bold}==>${reset}${bold} $1${reset}"; }
warn()  { echo -e "${yellow}${bold}warning:${reset} $1"; }

# ── uv ───────────────────────────────────────────────────────────────────────

if ! command -v uv &>/dev/null; then
    info "Installing uv…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # The uv installer creates this env file; source it so uv is available now
    # shellcheck source=/dev/null
    source "$HOME/.local/bin/env" 2>/dev/null || true
fi

if ! command -v uv &>/dev/null; then
    warn "uv was installed but is not on your PATH."
    warn "Add ~/.local/bin to your PATH and re-run this script."
    exit 1
fi

# ── spectral ─────────────────────────────────────────────────────────────────

PKG="spectral-mcp"

if uv tool list 2>/dev/null | grep -q '^spectral '; then
    info "Upgrading spectral…"
    uv tool install "$PKG" --upgrade
else
    info "Installing spectral…"
    uv tool install "$PKG"
fi

# ── verify ───────────────────────────────────────────────────────────────────

if ! command -v spectral &>/dev/null; then
    # ~/.local/bin may not be in PATH yet in this session
    export PATH="$HOME/.local/bin:$PATH"
fi

if spectral --version &>/dev/null; then
    ok "spectral $(spectral --version 2>&1 | awk '{print $NF}') is ready!"
else
    warn "Installation finished but 'spectral --version' failed."
    exit 1
fi

# ── shell completion ─────────────────────────────────────────────────────────

SHELL_NAME="$(basename "$SHELL" 2>/dev/null || true)"
EVAL_LINE='eval "$(spectral completion '"$SHELL_NAME"')"'

case "$SHELL_NAME" in
    bash)
        RC="$HOME/.bashrc"
        if [ -f "$RC" ] && ! grep -qF 'spectral completion' "$RC"; then
            echo "$EVAL_LINE" >> "$RC"
            info "Shell completion added to $RC"
        fi
        info "Run this to activate now:  source $RC"
        ;;
    zsh)
        RC="$HOME/.zshrc"
        if [ -f "$RC" ] && ! grep -qF 'spectral completion' "$RC"; then
            echo "$EVAL_LINE" >> "$RC"
            info "Shell completion added to $RC"
        fi
        info "Run this to activate now:  source $RC"
        ;;
esac

# ── PATH warning ─────────────────────────────────────────────────────────────

case ":$PATH:" in
    *:$HOME/.local/bin:*) ;;
    *)
        echo ""
        warn "~/.local/bin is not in your PATH."
        warn "Add it to your shell profile:"
        echo ""
        echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo ""
        ;;
esac

# ── next steps ───────────────────────────────────────────────────────────────

echo ""
echo -e "${bold}Next steps:${reset}"
echo "  1. Configure your LLM provider:  spectral config"
echo "     (supports Anthropic, OpenRouter, OpenAI, Ollama)"
echo "  2. Load the Chrome extension from the extension/ directory"
echo "     or use the MITM proxy: spectral capture proxy -a myapp"
echo "  3. Analyze traffic:  spectral mcp analyze myapp"
echo ""
