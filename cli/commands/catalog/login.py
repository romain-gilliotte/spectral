"""CLI command: spectral catalog login."""

from __future__ import annotations

import webbrowser

import click

from cli.formats.catalog import CatalogToken
from cli.helpers.console import console
from cli.helpers.github import (
    DeviceFlowError,
    get_github_user,
    poll_for_token,
    start_device_flow,
)
from cli.helpers.storage import load_catalog_token, write_catalog_token


@click.command()
def login() -> None:
    """Authenticate with GitHub for catalog operations."""

    existing = load_catalog_token()
    if existing:
        console.print(f"Already logged in as [bold]{existing.username}[/bold].")
        if not click.confirm("Re-authenticate?", default=False):
            return

    console.print("Starting GitHub Device Flow...")
    try:
        pending = start_device_flow()
    except Exception as exc:
        raise click.ClickException(f"Failed to start device flow: {exc}") from exc

    console.print(f"\nEnter code: [bold]{pending.user_code}[/bold]")
    console.print(f"at: {pending.verification_uri}\n")
    webbrowser.open(pending.verification_uri)

    console.print("Waiting for authorization...", style="dim")
    try:
        access_token = poll_for_token(pending)
    except DeviceFlowError as exc:
        raise click.ClickException(str(exc)) from exc

    user = get_github_user(access_token)
    username = user["login"]

    write_catalog_token(CatalogToken(access_token=access_token, username=username))
    console.print(f"[green]Logged in as [bold]{username}[/bold].[/green]")
