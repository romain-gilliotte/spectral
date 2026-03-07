"""GraphQL command group — registration only."""

from __future__ import annotations

import click

from cli.commands.graphql.analyze_cmd import analyze


@click.group("graphql")
def graphql_cmd() -> None:
    """GraphQL analysis commands."""


graphql_cmd.add_command(analyze)
