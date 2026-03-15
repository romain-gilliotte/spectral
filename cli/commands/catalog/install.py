"""CLI command: spectral catalog install."""

from __future__ import annotations

import re

import click

from cli.helpers.console import console


@click.command()
@click.argument("collection_ref")
def install(collection_ref: str) -> None:
    """Install a tool collection from the catalog.

    COLLECTION_REF is in the form <user>/<app> (e.g. romain/planity-com).
    """
    from cli.commands.catalog.types import CatalogInstallResult
    from cli.formats.catalog import CatalogManifest, CatalogSource
    from cli.formats.mcp_tool import ToolDefinition
    from cli.helpers.github import download_directory
    from cli.helpers.storage import ensure_app, update_app_meta, write_tools

    if not re.match(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$", collection_ref):
        raise click.ClickException(
            f"Invalid collection reference: '{collection_ref}'. "
            "Expected format: <user>/<app>"
        )

    username, app_name = collection_ref.split("/", 1)
    local_name = f"{username}__{app_name}"

    console.print(f"Installing [bold]{collection_ref}[/bold]...")

    try:
        files = download_directory(username, app_name)
    except Exception as exc:
        raise click.ClickException(
            f"Failed to download '{collection_ref}': {exc}"
        ) from exc

    if not files:
        raise click.ClickException(f"No files found for '{collection_ref}'.")

    # Parse manifest
    manifest: CatalogManifest | None = None
    tools: list[ToolDefinition] = []

    for entry in files:
        name = entry["name"]
        content = entry["content"]
        if name == "manifest.json":
            manifest = CatalogManifest.model_validate_json(content)
        else:
            try:
                tools.append(ToolDefinition.model_validate_json(content))
            except Exception as exc:
                console.print(
                    f"[yellow]Warning: skipping {name}: {exc}[/yellow]", style="dim"
                )

    if not tools:
        raise click.ClickException(f"No valid tools found in '{collection_ref}'.")

    display_name = manifest.display_name if manifest else app_name
    ensure_app(local_name, display_name=display_name)

    update_app_meta(
        local_name,
        catalog_source=CatalogSource(username=username, app_name=app_name),
    )

    write_tools(local_name, tools)

    result = CatalogInstallResult.from_tools(local_name, tools)
    console.print(
        f"[green]Installed {result.tool_count} tools as '{result.local_name}'.[/green]\n"
        f"Use them via the MCP server: spectral mcp stdio"
    )
