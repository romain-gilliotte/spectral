"""Auth cascade for MCP tool execution.

Provides token validation, auto-refresh, and interactive acquisition.
"""

from __future__ import annotations

import time
from types import ModuleType
from typing import Any

import click

from cli.formats.mcp_tool import TokenState
from cli.helpers.storage import (
    auth_script_path,
    load_token,
    write_token,
)


class AuthError(Exception):
    """Raised when authentication cannot be obtained."""


def is_token_valid(token: TokenState) -> bool:
    """Check if a token is still valid based on ``expires_at``."""
    if token.expires_at is None:
        return True
    return token.expires_at > time.time()


def get_auth(app_name: str) -> TokenState:
    """Auth cascade: valid token -> auto-refresh -> raise AuthError.

    Returns the validated/refreshed ``TokenState``.
    """
    token = load_token(app_name)

    # Step 1: Valid token
    if token is not None and is_token_valid(token):
        return token

    # Step 2: Auto-refresh
    if token is not None and token.refresh_token is not None:
        script = auth_script_path(app_name)
        if script.is_file():
            mod = load_auth_module(app_name)
            if hasattr(mod, "refresh_token"):
                try:
                    return refresh_auth(app_name, token)
                except Exception as exc:
                    click.echo(f"Warning: token refresh failed: {exc}", err=True)

    # Step 3: Auth required
    raise AuthError(
        f"No valid token for app '{app_name}'. "
        f"Run 'spectral auth login {app_name}' to authenticate."
    )


def refresh_auth(app_name: str, token: TokenState) -> TokenState:
    """Load auth_acquire.py and call ``refresh_token()``."""
    mod = load_auth_module(app_name)
    if not hasattr(mod, "refresh_token"):
        raise AuthError("Auth script does not define refresh_token()")

    result: dict[str, Any] = mod.refresh_token(token.refresh_token)
    new_token = _result_to_token_state(result)
    write_token(app_name, new_token)
    return new_token


def acquire_auth(app_name: str) -> TokenState:
    """Load auth_acquire.py and call ``acquire_token()`` interactively."""
    mod = load_auth_module(app_name)
    if not hasattr(mod, "acquire_token"):
        raise AuthError("Auth script does not define acquire_token()")

    result: dict[str, Any] = mod.acquire_token()
    new_token = _result_to_token_state(result)
    write_token(app_name, new_token)
    return new_token


captured_script_output: list[str] = []


def _capture_debug(*args: Any, **kwargs: Any) -> None:
    import io as _io

    buf = _io.StringIO()
    print(*args, file=buf, **kwargs)  # noqa: T201
    text = buf.getvalue()
    captured_script_output.append(text)


def load_auth_module(app_name: str) -> ModuleType:
    """Load auth_acquire.py as a module, injecting prompt utilities."""
    script = auth_script_path(app_name)
    if not script.is_file():
        raise AuthError(f"Auth script not found: {script}")

    source = script.read_text()
    mod = ModuleType(f"spectral_auth_{app_name}")

    # Inject helpers (prompt, messaging, debug)
    mod.prompt_text = _prompt_text  # type: ignore[attr-defined]
    mod.prompt_secret = _prompt_secret  # type: ignore[attr-defined]
    mod.tell_user = _tell_user  # type: ignore[attr-defined]
    mod.wait_user_confirmation = _wait_user_confirmation  # type: ignore[attr-defined]

    # Inject debug() for LLM troubleshooting (captured, shown on next fix attempt)
    captured_script_output.clear()
    mod.debug = _capture_debug  # type: ignore[attr-defined]

    code = compile(source, str(script), "exec")
    exec(code, mod.__dict__)
    return mod


def _prompt_text(label: str) -> str:
    """Prompt for text input."""
    return click.prompt(label)


def _prompt_secret(label: str) -> str:
    """Prompt for secret input (no echo)."""
    return click.prompt(label, hide_input=True)


def _tell_user(message: str) -> None:
    """Display a message to the user. Also captured for LLM debugging."""
    click.echo(message)
    captured_script_output.append(message + "\n")


def _wait_user_confirmation(message: str) -> None:
    """Display a message and wait for the user to press Enter."""
    _tell_user(message)
    click.pause("")


def _result_to_token_state(result: dict[str, Any]) -> TokenState:
    """Convert an auth function result dict to TokenState."""
    now = time.time()
    expires_at: float | None = None
    expires_in = result.get("expires_in")
    if expires_in is not None:
        expires_at = now + float(expires_in)

    return TokenState(
        headers=result.get("headers", {}),
        body_params=result.get("body_params", {}),
        refresh_token=result.get("refresh_token"),
        expires_at=expires_at,
        obtained_at=now,
    )
