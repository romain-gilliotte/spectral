"""Install Spectral MCP server into Claude Desktop and Claude Code."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
from typing import Any

import click


def _claude_desktop_config_path() -> Path:
    """Return the Claude Desktop config file path for the current platform."""
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    # Linux (and fallback)
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _resolve_spectral_path() -> str:
    """Return the absolute path to the ``spectral`` executable."""
    path = shutil.which("spectral")
    if not path:
        raise click.ClickException(
            "Could not find 'spectral' on PATH. "
            "Install it with the install script or 'uv tool install'."
        )
    return path


def _install_claude_desktop(spectral_path: str) -> bool:
    """Add a ``spectral`` entry to Claude Desktop's MCP config.

    Returns True if the config was written, False if Claude Desktop
    is not installed (config directory does not exist).
    """
    import json

    config_path = _claude_desktop_config_path()
    if not config_path.parent.exists():
        return False

    # Read existing config
    if config_path.exists():
        config: dict[str, Any] = json.loads(config_path.read_text())
    else:
        config: dict[str, Any] = {}

    if "mcpServers" not in config:
        config["mcpServers"] = {}
    config["mcpServers"]["spectral"] = {
        "command": spectral_path,
        "args": ["mcp", "stdio"],
    }

    config_path.write_text(json.dumps(config, indent=2) + "\n")
    return True


def _install_claude_code(spectral_path: str) -> bool:
    """Register Spectral as a user-scope MCP server in Claude Code.

    Returns True if the command succeeded, False if ``claude`` is not
    found on PATH.
    """
    import subprocess

    claude_path = shutil.which("claude")
    if not claude_path:
        return False

    subprocess.run(
        [
            claude_path,
            "mcp",
            "add",
            "-s",
            "user",
            "spectral",
            "--",
            spectral_path,
            "mcp",
            "stdio",
        ],
        check=True,
    )
    return True


@click.command()
@click.option(
    "--target",
    type=click.Choice(["claude-desktop", "claude-code"]),
    default=None,
    help="Target client. Default: install to all detected targets.",
)
def install(target: str | None) -> None:
    """Install the MCP server into Claude Desktop or Claude Code."""
    from cli.helpers.console import console

    spectral_path = _resolve_spectral_path()

    targets = [target] if target else ["claude-desktop", "claude-code"]
    installed: list[str] = []

    for t in targets:
        if t == "claude-desktop":
            if _install_claude_desktop(spectral_path):
                path = _claude_desktop_config_path()
                console.print(f"  Wrote {path}")
                installed.append("Claude Desktop")
            elif target:
                console.print(
                    "[yellow]Claude Desktop config directory not found — skipped.[/yellow]"
                )

        elif t == "claude-code":
            if _install_claude_code(spectral_path):
                console.print("  Registered via 'claude mcp add -s user spectral'")
                installed.append("Claude Code")
            elif target:
                console.print(
                    "[yellow]'claude' not found on PATH — skipped.[/yellow]"
                )

    if installed:
        console.print(
            f"\n[green]MCP server installed for: {', '.join(installed)}.[/green]"
        )
        console.print(f"  Executable: {spectral_path}")
    elif not target:
        console.print(
            "[yellow]No targets detected. Use --target to specify one.[/yellow]"
        )
