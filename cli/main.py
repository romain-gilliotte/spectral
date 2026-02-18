"""CLI entry point for spectral."""

from __future__ import annotations

import click
from dotenv import load_dotenv

from cli.analyze.cmd import analyze
from cli.android.cmd import android
from cli.capture.cmd import capture
from cli.client.cmd import call_command
from cli.generate.cmd import generate

load_dotenv()


@click.group()
@click.version_option(version="0.1.0", prog_name="spectral")
def cli() -> None:
    """Automatically discover and document web application APIs."""


cli.add_command(analyze)
cli.add_command(generate)
cli.add_command(call_command)
cli.add_command(capture)
cli.add_command(android)

if __name__ == "__main__":
    cli()
