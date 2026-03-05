"""CLI commands for Chrome Native Messaging integration."""

from __future__ import annotations

import shutil
import sys

import click

from cli.helpers.console import console


@click.group()
def extension() -> None:
    """Chrome extension integration: native messaging host."""


@extension.command()
def listen() -> None:
    """Native messaging host (called by Chrome, not by users directly)."""
    from cli.commands.extension.host import run_host

    run_host()


@extension.command()
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

    from cli.commands.extension.manifest import (
        generate_manifest,
        host_manifest_paths,
        write_wrapper_script,
        write_wrapper_script_python,
    )

    # Resolve spectral executable (must be absolute — Chrome won't have user PATH)
    spectral_path = shutil.which("spectral")
    if spectral_path:
        # shutil.which returns absolute path — use it directly
        script = write_wrapper_script(spectral_path)
    else:
        # Fallback: call via the current Python interpreter + module
        script = write_wrapper_script_python(sys.executable)


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
