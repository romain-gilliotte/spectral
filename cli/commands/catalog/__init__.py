"""Catalog command group — community tool catalog."""

from __future__ import annotations

import click

from cli.commands.catalog.install import install
from cli.commands.catalog.login import login
from cli.commands.catalog.logout import logout
from cli.commands.catalog.publish import publish
from cli.commands.catalog.search import search


@click.group()
def catalog() -> None:
    """Community tool catalog: publish, search, and install tools."""


catalog.add_command(install)
catalog.add_command(login)
catalog.add_command(logout)
catalog.add_command(publish)
catalog.add_command(search)
