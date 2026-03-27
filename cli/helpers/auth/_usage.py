from __future__ import annotations

import time
from typing import Any

import click

from cli.formats.mcp_tool import TokenState
from cli.helpers.auth._errors import AuthError, AuthScriptError, AuthScriptNotFound
from cli.helpers.auth._runtime import call_auth_module
from cli.helpers.storage import load_token, write_token


def get_auth(app_name: str) -> TokenState:
    """Auth cascade: valid token -> auto-refresh -> raise AuthError.

    Returns the validated/refreshed ``TokenState``.
    """
    token = load_token(app_name)

    # Step 1: Valid token
    if token is not None and _is_token_valid(token):
        return token

    # Step 2: Auto-refresh
    if token is not None and token.refresh_token is not None:
        try:
            return refresh_auth(app_name, token)
        except (AuthScriptError, AuthScriptNotFound) as exc:
            click.echo(f"Warning: token refresh failed: {exc}", err=True)

    # Step 3: Auth required
    raise AuthError(
        f"No valid token for app '{app_name}'. "
        f"Run 'spectral auth login {app_name}' to authenticate."
    )


def refresh_auth(
    app_name: str, token: TokenState, output: list[str] | None = None
) -> TokenState:
    """Load auth_acquire.py and call ``refresh_token()``."""

    result = call_auth_module(app_name, "refresh_token", output, token.refresh_token)
    new_token = _result_to_token_state(result)
    write_token(app_name, new_token)
    return new_token


def acquire_auth(app_name: str, output: list[str] | None = None) -> TokenState:
    """Load auth_acquire.py and call ``acquire_token()`` interactively."""

    result = call_auth_module(app_name, "acquire_token", output)
    new_token = _result_to_token_state(result)
    write_token(app_name, new_token)
    return new_token


def save_auth_result(app_name: str, result: dict[str, Any]) -> None:
    """Convert a raw auth function result to ``TokenState`` and persist it."""
    write_token(app_name, _result_to_token_state(result))


def _is_token_valid(token: TokenState) -> bool:
    """Check if a token is still valid based on ``expires_at``."""
    if token.expires_at is None:
        return True
    return token.expires_at > time.time()


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
