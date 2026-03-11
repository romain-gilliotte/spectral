"""CLI entry point for spectral."""

from __future__ import annotations

import importlib.metadata
import sys

import click

from cli.commands.android import android
from cli.commands.auth import auth
from cli.commands.capture import capture
from cli.commands.completion import completion
from cli.commands.config import config
from cli.commands.extension import extension
from cli.commands.graphql import graphql_cmd
from cli.commands.mcp import mcp
from cli.commands.openapi import openapi

# Hand-crafted spectrum analyzer waveform + "spectral" text
# fmt: off
_LOGO = (
    '                 \x1b[1;33m▄\x1b[0m   \x1b[1;33m▄\x1b[0m \x1b[1;33m▄\x1b[0m \x1b[1;33m▄\x1b[0m   \x1b[1;33m▄\x1b[0m\n'
    '           \x1b[33m▄\x1b[0m   \x1b[33m▄\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m▄\x1b[0m \x1b[1;33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m▄\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m▄\x1b[0m   \x1b[33m▄\x1b[0m\n'
    '       \x1b[2;33m▄\x1b[0m \x1b[2;33m▄\x1b[0m \x1b[33m█\x1b[0m \x1b[2;33m▄\x1b[0m \x1b[33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m█\x1b[0m \x1b[2;33m▄\x1b[0m \x1b[33m█\x1b[0m \x1b[2;33m▄\x1b[0m \x1b[2;33m▄\x1b[0m\n'
    '    \x1b[2;33m──\x1b[2;33m█\x1b[2;33m─\x1b[2;33m█\x1b[2;33m─\x1b[33m█\x1b[2;33m─\x1b[2;33m█\x1b[2;33m─\x1b[33m█\x1b[2;33m─\x1b[1;33m█\x1b[2;33m─\x1b[33m█\x1b[2;33m─\x1b[1;33m█\x1b[2;33m─\x1b[1;33m█\x1b[2;33m─\x1b[1;33m█\x1b[2;33m─\x1b[33m█\x1b[2;33m─\x1b[1;33m█\x1b[2;33m─\x1b[33m█\x1b[2;33m─\x1b[2;33m█\x1b[2;33m─\x1b[33m█\x1b[2;33m─\x1b[2;33m█\x1b[2;33m─\x1b[2;33m█\x1b[2;33m──────\x1b[0m \x1b[1;33mSpectral \x1b[2;33m─────────\x1b[0m\n'
    '       \x1b[2;33m▀\x1b[0m \x1b[2;33m▀\x1b[0m \x1b[33m█\x1b[0m \x1b[2;33m▀\x1b[0m \x1b[33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m█\x1b[0m \x1b[2;33m▀\x1b[0m \x1b[33m█\x1b[0m \x1b[2;33m▀\x1b[0m \x1b[2;33m▀\x1b[0m\n'
    '           \x1b[33m▀\x1b[0m   \x1b[33m▀\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m▀\x1b[0m \x1b[1;33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m▀\x1b[0m \x1b[1;33m█\x1b[0m \x1b[33m▀\x1b[0m   \x1b[33m▀\x1b[0m\n'
    '                 \x1b[1;33m▀\x1b[0m   \x1b[1;33m▀\x1b[0m \x1b[1;33m▀\x1b[0m \x1b[1;33m▀\x1b[0m   \x1b[1;33m▀\x1b[0m'
)
# fmt: on


class _SpectralGroup(click.Group):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
            click.echo(_LOGO)
            click.echo()
        super().format_help(ctx, formatter)


@click.group(cls=_SpectralGroup)
@click.version_option(version=importlib.metadata.version("spectral-mcp"), prog_name="spectral")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Automatically discover and document web application APIs."""
    import cli.helpers.llm as llm

    ctx.call_on_close(llm.print_usage_summary)


cli.add_command(android)
cli.add_command(auth)
cli.add_command(capture)
cli.add_command(completion)
cli.add_command(config)
cli.add_command(extension)
cli.add_command(graphql_cmd, "graphql")
cli.add_command(mcp)
cli.add_command(openapi)


if __name__ == "__main__":
    cli()
