"""API key resolution, model loading, and test model injection.

PydanticAI handles the Anthropic client, retry, and rate limiting internally.
This module is responsible only for ensuring the API key is available as an
environment variable (which PydanticAI reads automatically), resolving the
configured model, and providing a test-model override mechanism.
"""

from __future__ import annotations

import os
from typing import Any

import click

from cli.formats.config import DEFAULT_MODEL
import cli.helpers.storage as storage

_test_model: Any | None = None


def ensure_config() -> None:
    """Ensure ``ANTHROPIC_API_KEY`` is set in the environment.

    Resolution order: env var → config.json → interactive prompt (writes config).
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return

    config = storage.load_config()
    if config:
        os.environ["ANTHROPIC_API_KEY"] = config.api_key
        return

    from cli.formats.config import Config

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
    model = click.prompt("Model", default=DEFAULT_MODEL).strip()
    storage.write_config(Config(api_key=key, model=model))
    os.environ["ANTHROPIC_API_KEY"] = key


def load_model() -> str:
    """Return the configured model, falling back to ``DEFAULT_MODEL``."""
    config = storage.load_config()
    if config:
        return config.model
    return DEFAULT_MODEL


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
