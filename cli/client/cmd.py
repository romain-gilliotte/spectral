"""CLI command for calling API endpoints."""

from __future__ import annotations

import json
import sys

import click
from rich.table import Table

from cli.console import console


@click.command("call")
@click.argument("spec_path", type=click.Path(exists=True))
@click.argument("args", nargs=-1)
@click.option("--list", "list_endpoints", is_flag=True, default=False, help="List available endpoints")
@click.option("--token", default=None, help="Auth token")
@click.option("--username", default=None, help="Username for login")
@click.option("--password", default=None, help="Password for login")
@click.option("--base-url", default=None, help="Override base URL")
def call_command(spec_path: str, args: tuple[str, ...], list_endpoints: bool, token: str | None, username: str | None, password: str | None, base_url: str | None) -> None:
    """Call an API endpoint from an enriched spec.

    \b
    Examples:
      spectral call spec.json --list
      spectral call spec.json get_users
      spectral call spec.json get_user user_id=123 --token eyJ...
      spectral call spec.json login --username user@x.com --password secret
    """
    from typing import Any

    from cli.client import ApiClient

    try:
        client = ApiClient(
            spec_path,
            base_url=base_url,
            token=token,
            username=username,
            password=password,
        )
    except Exception as e:
        console.print(f"[red]Error initializing client: {e}[/red]")
        sys.exit(1)

    if list_endpoints or not args:
        endpoints: list[dict[str, Any]] = client.endpoints()
        table = Table(title="Available Endpoints")
        table.add_column("ID", style="cyan")
        table.add_column("Method")
        table.add_column("Path")
        table.add_column("Purpose")
        for ep in endpoints:
            table.add_row(ep["id"], ep["method"], ep["path"], ep["purpose"])
        console.print(table)
        return

    endpoint_id: str = args[0]
    kwargs: dict[str, str] = {}
    for arg in args[1:]:
        if "=" in arg:
            key, value = arg.split("=", 1)
            kwargs[key] = value
        else:
            console.print(f"[red]Invalid parameter format: {arg} (expected key=value)[/red]")
            sys.exit(1)

    try:
        result = client.call(endpoint_id, **kwargs)
        if result is not None:
            console.print_json(json.dumps(result, default=str))
        else:
            console.print("[dim]No content[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)
