"""Auth cascade for MCP tool execution.

Provides token validation, auto-refresh, and interactive acquisition.
"""

from __future__ import annotations

import getpass
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


def get_auth_headers(app_name: str) -> dict[str, str]:
    """Auth cascade: valid token -> auto-refresh -> raise AuthError.

    Returns auth headers to inject into HTTP requests.
    """
    token = load_token(app_name)

    # Step 1: Valid token
    if token is not None and is_token_valid(token):
        return dict(token.headers)

    # Step 2: Auto-refresh
    if token is not None and token.refresh_token is not None:
        script = auth_script_path(app_name)
        if script.is_file():
            mod = load_auth_module(app_name)
            if hasattr(mod, "refresh_token"):
                try:
                    new_token = refresh_auth(app_name, token)
                    return dict(new_token.headers)
                except Exception:
                    pass

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


def load_auth_module(app_name: str) -> ModuleType:
    """Load auth_acquire.py as a module, injecting prompt utilities."""
    script = auth_script_path(app_name)
    if not script.is_file():
        raise AuthError(f"Auth script not found: {script}")

    source = script.read_text()
    mod = ModuleType(f"spectral_auth_{app_name}")

    # Inject prompt utilities
    mod.prompt_text = _prompt_text  # type: ignore[attr-defined]
    mod.prompt_secret = _prompt_secret  # type: ignore[attr-defined]

    # Inject a print() that captures output for LLM debugging
    captured_script_output.clear()

    def _capture_print(*args: Any, **kwargs: Any) -> None:
        import io as _io

        buf = _io.StringIO()
        print(*args, file=buf, **kwargs)  # noqa: T201
        text = buf.getvalue()
        captured_script_output.append(text)

    mod.print = _capture_print  # type: ignore[attr-defined]

    code = compile(source, str(script), "exec")
    exec(code, mod.__dict__)
    return mod


def _prompt_text(label: str) -> str:
    """Prompt for text input via /dev/tty."""
    try:
        with open("/dev/tty") as tty:
            print(f"{label}: ", end="", flush=True)  # noqa: T201
            return tty.readline().strip()
    except OSError:
        return click.prompt(label)


def _prompt_secret(label: str) -> str:
    """Prompt for secret input via /dev/tty (no echo)."""
    try:
        return getpass.getpass(f"{label}: ")
    except OSError:
        return click.prompt(label, hide_input=True)


def _result_to_token_state(result: dict[str, Any]) -> TokenState:
    """Convert an auth function result dict to TokenState."""
    now = time.time()
    expires_at: float | None = None
    expires_in = result.get("expires_in")
    if expires_in is not None:
        expires_at = now + float(expires_in)

    return TokenState(
        headers=result["headers"],
        refresh_token=result.get("refresh_token"),
        expires_at=expires_at,
        obtained_at=now,
    )
