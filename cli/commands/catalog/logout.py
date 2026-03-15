"""CLI command: spectral catalog logout."""

from __future__ import annotations

import click

from cli.helpers.console import console


@click.command()
def logout() -> None:
    """Remove stored GitHub catalog token."""
    from cli.helpers.storage import delete_catalog_token

    if delete_catalog_token():
        console.print("[green]Logged out of catalog.[/green]")
    else:
        console.print("[dim]Not logged in. Nothing to remove.[/dim]")
