"""Auth command group — registration only."""

from __future__ import annotations

import click

from cli.commands.auth.analyze_acquire import analyze_acquire
from cli.commands.auth.analyze_refresh import analyze_refresh
from cli.commands.auth.extract import extract
from cli.commands.auth.login import login
from cli.commands.auth.logout import logout
from cli.commands.auth.refresh import refresh
from cli.commands.auth.set import set_token


@click.group()
def auth() -> None:
    """Authentication analysis and management."""


auth.add_command(analyze_acquire)
auth.add_command(analyze_refresh)
auth.add_command(extract)
auth.add_command(login)
auth.add_command(logout)
auth.add_command(refresh)
auth.add_command(set_token, "set")
