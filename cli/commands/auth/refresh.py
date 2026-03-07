"""CLI command: spectral auth refresh."""

from __future__ import annotations

import click

from cli.helpers.console import console


@click.command()
@click.argument("app_name")
def refresh(app_name: str) -> None:
    """Manually refresh the auth token for an app.

    Loads token.json, calls refresh_token(), and updates token.json.
    """
    from cli.helpers.auth_runtime import AuthError, refresh_auth
    from cli.helpers.storage import load_token, resolve_app, write_token

    resolve_app(app_name)

    token = load_token(app_name)
    if token is None:
        raise click.ClickException(
            f"No token found for '{app_name}'. Run 'spectral auth login {app_name}' first."
        )

    try:
        new_token = refresh_auth(app_name, token)
    except AuthError as exc:
        raise click.ClickException(str(exc)) from exc

    write_token(app_name, new_token)
    console.print("[green]Token refreshed successfully.[/green]")
