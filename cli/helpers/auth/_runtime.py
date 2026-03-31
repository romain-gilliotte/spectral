"""Auth cascade for MCP tool execution.

Provides token validation, auto-refresh, and interactive acquisition.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
import io
import re
from types import ModuleType
from typing import Any

import click

from cli.helpers.auth._errors import AuthScriptError, AuthScriptNotFound
from cli.helpers.storage import auth_script_path, refresh_script_path

_CACHEABLE_LABEL = re.compile(r"email|login|password|user", re.IGNORECASE)

_SCRIPT_PATHS = {
    "acquire_token": auth_script_path,
    "refresh_token": refresh_script_path,
}


def call_auth_module(
    app_name: str,
    fn: str,
    output: list[str] | None = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Load the appropriate auth script from disk and call *fn*.

    Routes to ``auth_acquire.py`` for ``acquire_token`` and
    ``auth_refresh.py`` for ``refresh_token``.
    """

    path_fn = _SCRIPT_PATHS.get(fn, auth_script_path)
    script = path_fn(app_name)
    if not script.is_file():
        raise AuthScriptNotFound()

    return call_auth_module_source(
        script.read_text(), fn, output, *args, filename=str(script), **kwargs
    )


def call_auth_module_source(
    source: str,
    fn: str,
    output: list[str] | None = None,
    *args: Any,
    filename: str = "<auth-acquire>",
    prompt_cache: dict[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    """Execute an auth script from *source* and call *fn*.

    This is the low-level entry point used both by ``call_auth_module``
    (which reads from disk) and by the analyze command (which tests
    scripts before saving them).

    When *prompt_cache* is provided, credential prompts whose label
    matches common patterns (email, login, password, user) are cached
    and replayed on subsequent calls.  OTP / one-time codes are never
    cached.
    """

    mod = ModuleType("spectral_auth")

    # Inject helpers (prompt, messaging, debug)
    mod.prompt_text = partial(_cached_prompt, _prompt_text, prompt_cache)  # type: ignore[attr-defined]
    mod.prompt_secret = partial(_cached_prompt, _prompt_secret, prompt_cache)  # type: ignore[attr-defined]
    mod.tell_user = partial(_tell_user, output)  # type: ignore[attr-defined]
    mod.wait_user_confirmation = partial(_wait_user_confirmation, output)  # type: ignore[attr-defined]
    mod.debug = partial(_capture_debug, output)  # type: ignore[attr-defined]

    try:
        code = compile(source, filename, "exec")
        exec(code, mod.__dict__)
    except Exception as exc:
        raise AuthScriptError(f"Auth script failed to load: {exc}") from exc

    if not hasattr(mod, fn):
        raise AuthScriptError(f"Auth script does not define {fn}()")

    try:
        return getattr(mod, fn)(*args, **kwargs)
    except Exception as exc:
        raise AuthScriptError("Auth script crashed at runtime") from exc


def _cached_prompt(
    prompt_fn: Callable[[str], str],
    cache: dict[str, str] | None,
    label: str,
) -> str:
    """Prompt with optional caching for credential labels."""
    if cache is not None and label in cache:
        return cache[label]
    value = prompt_fn(label)
    if cache is not None and _CACHEABLE_LABEL.search(label):
        cache[label] = value
    return value


def _capture_debug(output: list[str] | None, *args: Any, **kwargs: Any) -> None:
    if output is not None:
        buf = io.StringIO()
        print(*args, file=buf, **kwargs)  # noqa: T201
        output.append(buf.getvalue())


def _tell_user(output: list[str] | None, message: str) -> None:
    click.echo(message)

    if output is not None:
        output.append(message + "\n")


def _wait_user_confirmation(output: list[str] | None, message: str) -> None:
    _tell_user(output, message)
    click.pause("")


def _prompt_text(label: str) -> str:
    """Prompt for text input."""
    import questionary

    return questionary.text(label + ":").unsafe_ask()


def _prompt_secret(label: str) -> str:
    """Prompt for secret input (masked with *)."""
    import questionary

    return questionary.password(label + ":").unsafe_ask()
