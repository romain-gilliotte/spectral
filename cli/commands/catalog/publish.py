"""CLI command: spectral catalog publish."""

from __future__ import annotations

import importlib.metadata

import click

from cli.helpers.console import console


@click.command()
@click.argument("app_name")
def publish(app_name: str) -> None:
    """Publish an app's tools to the community catalog."""
    from cli.formats.catalog import CatalogManifest
    from cli.helpers.catalog_api import CatalogAPIError, publish as api_publish
    from cli.helpers.storage import (
        auth_script_path,
        list_tools,
        load_app_meta,
        load_catalog_token,
        resolve_app,
    )

    # 1. Verify app exists and has tools
    resolve_app(app_name)
    tools = list_tools(app_name)
    if not tools:
        raise click.ClickException(f"App '{app_name}' has no tools to publish.")

    # 2. Verify logged in
    token = load_catalog_token()
    if not token:
        raise click.ClickException(
            "Not logged in. Run 'spectral community login' first."
        )

    # 3. Reject catalog-installed apps (double underscore)
    if "__" in app_name:
        raise click.ClickException(
            "Cannot publish catalog-installed tools. "
            "Publish your own analyzed apps instead."
        )

    meta = load_app_meta(app_name)

    manifest = CatalogManifest(
        display_name=meta.display_name or app_name,
        description=f"MCP tools for {meta.display_name or app_name}",
        spectral_version=importlib.metadata.version("spectral-mcp"),
    )

    script_path = auth_script_path(app_name)
    auth_script = script_path.read_text() if script_path.is_file() else None

    label = f"Publishing [bold]{app_name}[/bold] ({len(tools)} tools"
    if auth_script is not None:
        label += ", with auth script"
    label += ")..."
    console.print(label)

    try:
        result = api_publish(
            github_token=token.access_token,
            app_name=app_name,
            manifest=manifest.model_dump(),
            tools=[t.model_dump() for t in tools],
            auth_script=auth_script,
        )
    except CatalogAPIError as exc:
        raise click.ClickException(f"Publish failed: {exc.message}") from exc

    pr_url = result.get("pr_url", "")
    if result.get("pr_created"):
        console.print(f"\n[green]Pull request created successfully.[/green]")
    else:
        console.print(f"\n[green]Pull request updated successfully.[/green]")
    console.print(f"  {pr_url}\n")
    console.print(
        "Your contribution will be reviewed before being merged.\n"
        "Once approved, your tools will be available in the catalog.\n"
        "You can republish at any time to update your tools."
    )
