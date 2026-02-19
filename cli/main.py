"""CLI entry point for spectral."""

from __future__ import annotations

import click
from dotenv import load_dotenv

from cli.commands.analyze.cmd import analyze
from cli.commands.android.cmd import android
from cli.commands.capture.cmd import capture

load_dotenv()


@click.group()
@click.version_option(version="0.1.0", prog_name="spectral")
def cli() -> None:
    """Automatically discover and document web application APIs."""


cli.add_command(analyze)
cli.add_command(capture)
cli.add_command(android)

if __name__ == "__main__":
    cli()
