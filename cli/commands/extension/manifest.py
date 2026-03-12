"""Chrome Native Messaging host manifest generation."""

from __future__ import annotations

from pathlib import Path
import shlex
import shutil
import sys

import click

from cli.helpers.storage import store_root

HOST_NAME = "com.spectral.capture_host"
MANIFEST_FILENAME = f"{HOST_NAME}.json"

# Browser → config dir (relative to ~) per OS.
_BROWSER_DIRS: dict[str, dict[str, str]] = {
    "linux": {
        "chrome": ".config/google-chrome/NativeMessagingHosts",
        "chromium": ".config/chromium/NativeMessagingHosts",
        "brave": ".config/BraveSoftware/Brave-Browser/NativeMessagingHosts",
        "edge": ".config/microsoft-edge/NativeMessagingHosts",
    },
    "darwin": {
        "chrome": "Library/Application Support/Google/Chrome/NativeMessagingHosts",
        "chromium": "Library/Application Support/Chromium/NativeMessagingHosts",
        "brave": "Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts",
        "edge": "Library/Application Support/Microsoft Edge/NativeMessagingHosts",
    },
}


def _os_key() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def host_manifest_paths(browser: str | None = None) -> list[Path]:
    """Return manifest path(s) for the given browser, or all detected browsers."""
    os_key = _os_key()
    dirs = _BROWSER_DIRS[os_key]
    home = Path.home()

    if browser:
        browser = browser.lower()
        if browser not in dirs:
            raise ValueError(f"Unknown browser '{browser}'. Known: {', '.join(dirs)}")
        return [home / dirs[browser] / MANIFEST_FILENAME]

    # Auto-detect: return paths for browsers whose config dir exists.
    result: list[Path] = []
    for _browser_name, rel in dirs.items():
        parent = home / rel
        if parent.parent.exists():
            result.append(parent / MANIFEST_FILENAME)
    return result


def generate_manifest(extension_id: str, host_path: str) -> dict[str, object]:
    """Build the native messaging host manifest JSON."""
    return {
        "name": HOST_NAME,
        "description": "Spectral capture host — receives captures from the Chrome extension",
        "path": host_path,
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }


def _wrapper_script_path() -> Path:
    """Return the path for the wrapper shell script."""
    return store_root() / "native_host.sh"


def _write_wrapper_script(spectral_path: str) -> Path:
    """Write a wrapper shell script that invokes ``spectral extension listen``.

    Uses the ``spectral`` entry-point script directly (must be an absolute path).
    Returns the script path.
    """
    script = _wrapper_script_path()
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f"#!/bin/sh\nexec {shlex.quote(spectral_path)} extension listen\n")
    script.chmod(0o755)
    return script


def _write_wrapper_script_python(python_path: str) -> Path:
    """Write a wrapper that invokes ``python -m cli.main extension listen``.

    Fallback when ``spectral`` is not on PATH (e.g. running via ``uv run``).
    Returns the script path.
    """
    script = _wrapper_script_path()
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        f"#!/bin/sh\nexec {shlex.quote(python_path)} -m cli.main extension listen\n"
    )
    script.chmod(0o755)
    return script


@click.command()
@click.option(
    "--extension-id",
    required=True,
    help="Chrome extension ID (from chrome://extensions).",
)
@click.option(
    "--browser",
    default=None,
    help="Target browser (chrome, chromium, brave, edge). Default: auto-detect.",
)
def install(extension_id: str, browser: str | None) -> None:
    """Install the native messaging host manifest for Chrome."""
    import json

    from cli.helpers.console import console

    # Resolve spectral executable (must be absolute — Chrome won't have user PATH)
    spectral_path = shutil.which("spectral")
    if spectral_path:
        # shutil.which returns absolute path — use it directly
        script = _write_wrapper_script(spectral_path)
    else:
        # Fallback: call via the current Python interpreter + module
        script = _write_wrapper_script_python(sys.executable)

    # Generate and write manifests
    paths = host_manifest_paths(browser)
    if not paths:
        raise click.ClickException(
            "No supported browsers detected. Use --browser to specify one."
        )

    manifest = generate_manifest(extension_id, str(script))
    manifest_json = json.dumps(manifest, indent=2)

    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest_json)
        console.print(f"  Wrote {path}")

    console.print(f"\n[green]Native messaging host installed.[/green]")
    console.print(f"  Wrapper: {script}")
    console.print(f"  Host name: {manifest['name']}")
