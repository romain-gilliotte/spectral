"""Shared fixtures and helpers for auth tests."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from cli.formats.mcp_tool import TokenState
from cli.helpers.storage import auth_script_path, ensure_app

# ---------------------------------------------------------------------------
# Script constants
# ---------------------------------------------------------------------------

VALID_SCRIPT = """\
def acquire_token():
    return {"headers": {"Authorization": "Bearer test-token"}}

def refresh_token(old):
    return {"headers": {"Authorization": "Bearer refreshed"}, "refresh_token": old}
"""

ACQUIRE_ONLY_SCRIPT = """\
def acquire_token():
    return {"headers": {"Authorization": "Bearer acquired"}}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_token(
    *,
    headers: dict[str, str] | None = None,
    body_params: dict[str, str] | None = None,
    refresh_token: str | None = None,
    expires_at: float | None = None,
    obtained_at: float | None = None,
) -> TokenState:
    """Build a TokenState with sensible defaults."""
    return TokenState(
        headers=headers or {"Authorization": "Bearer default"},
        body_params=body_params or {},
        refresh_token=refresh_token,
        expires_at=expires_at,
        obtained_at=obtained_at or time.time(),
    )


def write_auth_script(app_name: str, source: str) -> Path:
    """Write *source* as the auth script for *app_name* and return its path."""
    path = auth_script_path(app_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Set up an isolated SPECTRAL_HOME with a 'testapp' and return the app name."""
    monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
    ensure_app("testapp")
    return "testapp"
