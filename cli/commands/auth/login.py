"""CLI command: spectral auth login."""

from __future__ import annotations

import traceback

import click

from cli.helpers.auth import AuthScriptError, AuthScriptNotFound, acquire_auth
from cli.helpers.console import console
from cli.helpers.storage import resolve_app


@click.command()
@click.argument("app_name")
def login(app_name: str) -> None:
    """Run interactive authentication for an app.

    Loads auth_acquire.py, calls acquire_token(), and writes token.json.
    If the script fails, directs the user to re-run ``auth analyze``.
    """

    console.print(f"[bold]Logging in to {app_name}...[/bold]")
    resolve_app(app_name)

    output: list[str] = []
    try:
        acquire_auth(app_name, output=output)
        console.print("[green]Login successful. Token saved.[/green]")

    except AuthScriptNotFound:
        raise click.ClickException(
            f"Auth script not found for '{app_name}'. "
            f"Run 'spectral auth analyze-acquire {app_name}' to generate one."
        )

    except AuthScriptError:
        console.print("[red]Login failed:[/red]")
        console.print(traceback.format_exc())
        raise click.ClickException(
            f"Auth script failed for '{app_name}'. "
            f"Run 'spectral auth analyze-acquire {app_name}' to regenerate."
        )
