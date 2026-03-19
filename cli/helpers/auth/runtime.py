"""Auth cascade for MCP tool execution.

Provides token validation, auto-refresh, and interactive acquisition.
"""

from __future__ import annotations

from functools import partial
import io
from types import ModuleType
from typing import Any

import click

from cli.helpers.auth.errors import AuthScriptError, AuthScriptNotFound
from cli.helpers.storage import auth_script_path


def call_auth_module(
    app_name: str,
    fn: str,
    output: list[str] | None = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Load auth_acquire.py as a module, injecting prompt utilities."""

    script = auth_script_path(app_name)
    if not script.is_file():
        raise AuthScriptNotFound()

    source = script.read_text()
    mod = ModuleType(f"spectral_auth_{app_name}")

    # Inject helpers (prompt, messaging, debug)
    mod.prompt_text = _prompt_text  # type: ignore[attr-defined]
    mod.prompt_secret = _prompt_secret  # type: ignore[attr-defined]
    mod.tell_user = partial(_tell_user, output)  # type: ignore[attr-defined]
    mod.wait_user_confirmation = partial(_wait_user_confirmation, output)  # type: ignore[attr-defined]
    mod.debug = partial(_capture_debug, output)  # type: ignore[attr-defined]

    try:
        code = compile(source, str(script), "exec")
        exec(code, mod.__dict__)
    except Exception as exc:
        raise AuthScriptError(f"Auth script failed to load: {exc}") from exc

    if not hasattr(mod, fn):
        raise AuthScriptError(f"Auth script does not define {fn}()")

    try:
        return getattr(mod, fn)(*args, **kwargs)
    except Exception as exc:
        raise AuthScriptError("Auth script crashed at runtime") from exc


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
    return click.prompt(label)


def _prompt_secret(label: str) -> str:
    """Prompt for secret input (no echo)."""
    return click.prompt(label, hide_input=True)
