"""API key resolution and test model injection.

PydanticAI handles the Anthropic client, retry, and rate limiting internally.
This module is responsible only for ensuring the API key is available as an
environment variable (which PydanticAI reads automatically) and for providing
a test-model override mechanism.
"""

from __future__ import annotations

import os
from typing import Any

import click

import cli.helpers.storage as storage

_test_model: Any | None = None


def ensure_api_key() -> None:
    """Ensure ``ANTHROPIC_API_KEY`` is set in the environment.

    Resolution order: env var → stored key file → interactive prompt.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return

    key = storage.load_api_key()
    if not key:
        click.echo(
            "\nTo use this command, Spectral needs an Anthropic API key.\n"
            "You can create one at https://console.anthropic.com/settings/keys\n"
            f"\nThe key will be saved to {storage.store_root() / 'api_key'}\n"
        )
        key = click.prompt("API key", hide_input=True).strip()
        if not key.startswith("sk-ant-"):
            raise click.ClickException(
                "Invalid API key format (expected a key starting with 'sk-ant-')."
            )
        storage.write_api_key(key)

    os.environ["ANTHROPIC_API_KEY"] = key


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
