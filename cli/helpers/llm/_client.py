"""Config resolution and test model injection.

PydanticAI handles the Anthropic client, retry, and rate limiting internally.
This module provides ``get_or_create_config()`` which returns the stored config
or interactively prompts for one, and a test-model override mechanism.
"""

from __future__ import annotations

from typing import Any

import click

from cli.formats.config import Config
import cli.helpers.storage as storage

_test_model: Any | None = None


def get_or_create_config() -> Config:
    """Return config from disk, or create it interactively."""
    config = storage.load_config()
    if config:
        return config

    click.echo(
        "\nTo use this command, Spectral needs an Anthropic API key.\n"
        "You can create one at https://console.anthropic.com/settings/keys\n"
        f"\nThe config will be saved to {storage.config_path()}\n"
    )
    key = click.prompt("API key", hide_input=True).strip()
    if not key.startswith("sk-ant-"):
        raise click.ClickException(
            "Invalid API key format (expected a key starting with 'sk-ant-')."
        )
    model = click.prompt(
        "Model", default=str(Config.model_fields["model"].default)
    ).strip()
    config = Config(api_key=key, model=model)
    storage.write_config(config)
    return config


def set_test_model(model: Any) -> None:
    """Inject a test model (e.g. ``FunctionModel``) used by all conversations."""
    global _test_model
    _test_model = model


def get_test_model() -> Any | None:
    """Return the currently active test model, or ``None``."""
    return _test_model


def clear_test_model() -> None:
    """Clear the test model override."""
    global _test_model
    _test_model = None
