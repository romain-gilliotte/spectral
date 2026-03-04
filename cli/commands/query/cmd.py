"""CLI commands for auth management: login, refresh."""

from __future__ import annotations

import click

from cli.helpers.console import console


@click.group()
def query() -> None:
    """Auth management: login and refresh tokens for apps."""


@query.command()
@click.argument("app_name")
def login(app_name: str) -> None:
    """Run interactive authentication for an app.

    Loads auth_acquire.py, calls acquire_token(), and writes token.json.
    """
    from cli.commands.mcp.auth import acquire_auth
    from cli.helpers.storage import resolve_app, write_token

    resolve_app(app_name)

    console.print(f"[bold]Logging in to {app_name}...[/bold]")
    token = acquire_auth(app_name)
    write_token(app_name, token)
    console.print("[green]Login successful. Token saved.[/green]")


@query.command()
@click.argument("app_name")
def refresh(app_name: str) -> None:
    """Manually refresh the auth token for an app.

    Loads token.json, calls refresh_token(), and updates token.json.
    """
    from cli.commands.mcp.auth import AuthError, refresh_auth
    from cli.helpers.storage import load_token, resolve_app, write_token

    resolve_app(app_name)

    token = load_token(app_name)
    if token is None:
        raise click.ClickException(
            f"No token found for '{app_name}'. Run 'spectral query login {app_name}' first."
        )

    try:
        new_token = refresh_auth(app_name, token)
    except AuthError as exc:
        raise click.ClickException(str(exc)) from exc

    write_token(app_name, new_token)
    console.print("[green]Token refreshed successfully.[/green]")
