"""CLI entry point for spectral."""

from __future__ import annotations

import click

from cli.commands.android import android
from cli.commands.auth import auth
from cli.commands.capture import capture
from cli.commands.extension import extension
from cli.commands.graphql import graphql_cmd
from cli.commands.mcp import mcp
from cli.commands.openapi import openapi
import cli.helpers.llm as llm


@click.group()
@click.version_option(version="0.1.0", prog_name="spectral")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Automatically discover and document web application APIs."""
    ctx.call_on_close(llm.print_usage_summary)


cli.add_command(openapi)
cli.add_command(graphql_cmd, "graphql")
cli.add_command(mcp)
cli.add_command(auth)
cli.add_command(capture)
cli.add_command(extension)
cli.add_command(android)

if __name__ == "__main__":
    cli()
