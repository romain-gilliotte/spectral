"""CLI command: spectral auth logout."""

from __future__ import annotations

import click

from cli.helpers.console import console
from cli.helpers.storage import delete_token, resolve_app


@click.command()
@click.argument("app_name")
def logout(app_name: str) -> None:
    """Remove stored token for an app."""

    resolve_app(app_name)

    if delete_token(app_name):
        console.print(f"[green]Logged out of {app_name}. Token removed.[/green]")
    else:
        console.print(f"[dim]No token found for '{app_name}'. Nothing to remove.[/dim]")
