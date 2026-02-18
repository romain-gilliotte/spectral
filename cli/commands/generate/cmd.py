"""CLI command for the generate stage."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import click

from cli.helpers.console import console
from cli.formats.api_spec import ApiSpec


@click.command()
@click.argument("spec_path", type=click.Path(exists=True))
@click.option(
    "--type",
    "output_type",
    required=True,
    type=click.Choice(
        ["openapi", "mcp-server", "python-client", "markdown-docs", "curl-scripts"]
    ),
    help="Output type to generate",
)
@click.option("-o", "--output", required=True, help="Output path (file or directory)")
def generate(spec_path: str, output_type: str, output: str) -> None:
    """Generate outputs from an enriched API spec."""
    console.print(f"[bold]Loading API spec:[/bold] {spec_path}")
    spec = ApiSpec.model_validate_json(Path(spec_path).read_text())

    generators: dict[str, Callable[[ApiSpec, str], None]] = {
        "openapi": _generate_openapi,
        "mcp-server": _generate_mcp_server,
        "python-client": _generate_python_client,
        "markdown-docs": _generate_markdown_docs,
        "curl-scripts": _generate_curl_scripts,
    }

    gen_func = generators[output_type]
    gen_func(spec, output)
    console.print(f"[green]Generated {output_type} at {output}[/green]")


def _generate_openapi(spec: ApiSpec, output: str) -> None:
    from cli.commands.generate.openapi import generate_openapi

    generate_openapi(spec, output)


def _generate_mcp_server(spec: ApiSpec, output: str) -> None:
    from cli.commands.generate.mcp_server import generate_mcp_server

    generate_mcp_server(spec, output)


def _generate_python_client(spec: ApiSpec, output: str) -> None:
    from cli.commands.generate.python_client import generate_python_client

    generate_python_client(spec, output)


def _generate_markdown_docs(spec: ApiSpec, output: str) -> None:
    from cli.commands.generate.markdown_docs import generate_markdown_docs

    generate_markdown_docs(spec, output)


def _generate_curl_scripts(spec: ApiSpec, output: str) -> None:
    from cli.commands.generate.curl_scripts import generate_curl_scripts

    generate_curl_scripts(spec, output)
