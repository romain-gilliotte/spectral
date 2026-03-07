"""OpenAPI command group — registration only."""

from __future__ import annotations

import click

from cli.commands.openapi.analyze_cmd import analyze


@click.group("openapi")
def openapi() -> None:
    """OpenAPI (REST) analysis commands."""


openapi.add_command(analyze)
