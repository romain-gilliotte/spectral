"""CLI entry point for spectral."""

from __future__ import annotations

import click

from cli.commands.android.cmd import android
from cli.commands.auth.cmd import auth
from cli.commands.capture.cmd import capture
from cli.commands.extension.cmd import extension
from cli.commands.graphql.cmd import graphql_cmd
from cli.commands.mcp.cmd import mcp
from cli.commands.openapi.cmd import openapi


@click.group()
@click.version_option(version="0.1.0", prog_name="spectral")
def cli() -> None:
    """Automatically discover and document web application APIs."""


cli.add_command(openapi)
cli.add_command(graphql_cmd, "graphql")
cli.add_command(mcp)
cli.add_command(auth)
cli.add_command(capture)
cli.add_command(extension)
cli.add_command(android)

if __name__ == "__main__":
    cli()
