"""LLM client lifecycle and transport layer (retry, semaphore, rate limiting)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import os
from typing import Any

import click
import litellm

from cli.helpers.console import console
import cli.helpers.storage as storage

SendFn = Callable[..., Coroutine[Any, Any, Any]]

_send_fn: SendFn | None = None
_semaphore: asyncio.Semaphore | None = None
_setup_done: bool = False

MAX_CONCURRENT = 5
MAX_RETRIES = 3
FALLBACK_BACKOFF = 2.0  # seconds, doubled each retry

# Suppress litellm's noisy logging
litellm.suppress_debug_info = True


def setup(send_fn: SendFn | None = None) -> None:
    """Ensure the LLM backend is configured.

    With *send_fn*, inject a mock callable for tests.
    Without arguments, resolve the API key from env / storage / interactive prompt.
    """
    global _send_fn, _setup_done

    if send_fn is not None:
        _send_fn = send_fn
        _setup_done = True
        return

    if _setup_done:
        return

    # If no env var key for any known provider, try stored config, then prompt
    llm_config = storage.load_llm_config()
    if not _has_provider_key_in_env():
        if llm_config and llm_config.get("api_key"):
            pass  # will be passed via api_key= at call time
        else:
            click.echo(
                "\nTo use this command, Spectral needs an LLM API key.\n"
                "Examples: Anthropic, OpenAI, OpenRouter, etc.\n"
                f"\nThe key will be saved to {storage.store_root() / 'llm.json'}\n"
            )
            key = click.prompt("API key", hide_input=True).strip()
            if not key:
                raise click.ClickException("API key cannot be empty.")
            model = click.prompt(
                "Model (LiteLLM format, e.g. anthropic/claude-sonnet-4-5-20250929)",
                default="anthropic/claude-sonnet-4-5-20250929",
            ).strip()
            storage.write_llm_config(api_key=key, model=model)

    _setup_done = True


def clear() -> None:
    """Clear the module-level state (for tests)."""
    global _send_fn, _semaphore, _setup_done
    _send_fn = None
    _semaphore = None
    _setup_done = False


def get_stored_api_key() -> str | None:
    """Return the stored API key from llm.json, if any."""
    config = storage.load_llm_config()
    if config:
        return config.get("api_key")
    return None


def get_stored_model() -> str | None:
    """Return the stored model from llm.json, if any."""
    config = storage.load_llm_config()
    if config:
        return config.get("model")
    return None


def _has_provider_key_in_env() -> bool:
    """Check if any known LLM provider key is set as an env var."""
    env_keys = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "AZURE_API_KEY",
        "GEMINI_API_KEY",
        "COHERE_API_KEY",
    ]
    return any(os.environ.get(k) for k in env_keys)


def _get_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore, lazily creating it."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    return _semaphore


def _parse_retry_after(exc: Exception) -> float | None:
    """Extract ``retry-after`` seconds from an error response."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


async def send(*, label: str = "", **kwargs: Any) -> Any:
    """Call the LLM with semaphore gating and rate-limit retry."""
    from cli.helpers.llm._cost import record_usage

    if not _setup_done:
        setup()

    # Inject stored API key if no env var is set
    if "api_key" not in kwargs:
        stored_key = get_stored_api_key()
        if stored_key and not _has_provider_key_in_env():
            kwargs["api_key"] = stored_key

    semaphore = _get_semaphore()
    delay = FALLBACK_BACKOFF

    async with semaphore:
        for attempt in range(MAX_RETRIES + 1):
            try:
                if _send_fn is not None:
                    response = await _send_fn(**kwargs)
                else:
                    response = await litellm.acompletion(**kwargs)  # pyright: ignore[reportUnknownMemberType]
                record_usage(response, label, kwargs.get("model", ""))
                return response
            except litellm.RateLimitError as exc:  # pyright: ignore[reportPrivateImportUsage]
                if attempt >= MAX_RETRIES:
                    tag = f" ({label})" if label else ""
                    console.print(
                        f"  [red]Rate limit exceeded{tag}, "
                        f"giving up after {MAX_RETRIES} retries[/red]"
                    )
                    raise

                wait = _parse_retry_after(exc)
                if wait is None:
                    wait = delay
                    delay *= 2

                tag = f" ({label})" if label else ""
                console.print(
                    f"  [yellow]Rate limited{tag}, "
                    f"retrying in {wait:.1f}s...[/yellow]"
                )
                await asyncio.sleep(wait)

    raise RuntimeError("unreachable")  # pragma: no cover
