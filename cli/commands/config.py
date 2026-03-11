"""CLI command: spectral config."""

from __future__ import annotations

import click

from cli.formats.config import DEFAULT_MODEL, Config
from cli.helpers.console import console
from cli.helpers.storage import config_path, load_config, write_config


@click.command()
def config() -> None:
    """Configure API key and model."""
    existing = load_config()

    click.echo(
        "\nSpectral configuration\n"
        f"Config file: {config_path()}\n"
    )

    if existing:
        console.print(f"  Current API key: {existing.api_key[:12]}...")
        console.print(f"  Current model:   {existing.model}\n")

    default_key = existing.api_key if existing else ""
    key = click.prompt("API key", default=default_key, hide_input=True).strip()
    if not key.startswith("sk-ant-"):
        raise click.ClickException(
            "Invalid API key format (expected a key starting with 'sk-ant-')."
        )

    default_model = existing.model if existing else DEFAULT_MODEL
    model = click.prompt("Model", default=default_model).strip()

    write_config(Config(api_key=key, model=model))
    console.print(f"\n[green]Config saved to {config_path()}[/green]")
