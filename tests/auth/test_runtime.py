# pyright: reportPrivateUsage=false
"""Tests for cli.helpers.auth.runtime — auth cascade for MCP tool execution."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from cli.helpers.auth.errors import AuthScriptError, AuthScriptNotFound
from cli.helpers.auth.runtime import call_auth_module
from cli.helpers.storage import auth_script_path

# ---------------------------------------------------------------------------
# Constants
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

DEBUG_SCRIPT = """\
def acquire_token():
    debug("hello")
    return {"headers": {}}
"""

TELL_USER_SCRIPT = """\
def acquire_token():
    tell_user("msg")
    return {"headers": {}}
"""

PROMPT_TEXT_SCRIPT = """\
def acquire_token():
    value = prompt_text("label")
    return {"headers": {"X-Value": value}}
"""

SYNTAX_ERROR_SCRIPT = """\
def acquire_token(
    return {}
"""

CRASH_SCRIPT = """\
def acquire_token():
    raise RuntimeError("boom")
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_script(app_name: str, source: str) -> None:
    path = auth_script_path(app_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


# ---------------------------------------------------------------------------
# TestCallAuthModule
# ---------------------------------------------------------------------------


class TestCallAuthModule:
    def test_acquire_token_success(self, app_home: str) -> None:
        _write_script(app_home, VALID_SCRIPT)
        result = call_auth_module(app_home, "acquire_token")
        assert isinstance(result, dict)
        assert result["headers"]["Authorization"] == "Bearer test-token"

    def test_refresh_token_success(self, app_home: str) -> None:
        _write_script(app_home, VALID_SCRIPT)
        result = call_auth_module(app_home, "refresh_token", None, "old-rt")
        assert isinstance(result, dict)
        assert result["headers"]["Authorization"] == "Bearer refreshed"
        assert result["refresh_token"] == "old-rt"

    def test_script_not_found_raises(self, app_home: str) -> None:
        with pytest.raises(AuthScriptNotFound):
            call_auth_module(app_home, "acquire_token")

    def test_syntax_error_raises_script_error(self, app_home: str) -> None:
        _write_script(app_home, SYNTAX_ERROR_SCRIPT)
        with pytest.raises(AuthScriptError, match="failed to load"):
            call_auth_module(app_home, "acquire_token")

    def test_runtime_crash_raises_script_error(self, app_home: str) -> None:
        _write_script(app_home, CRASH_SCRIPT)
        with pytest.raises(AuthScriptError, match="crashed at runtime"):
            call_auth_module(app_home, "acquire_token")

    def test_missing_function_raises_script_error(self, app_home: str) -> None:
        _write_script(app_home, ACQUIRE_ONLY_SCRIPT)
        with pytest.raises(AuthScriptError, match="does not define refresh_token"):
            call_auth_module(app_home, "refresh_token")


# ---------------------------------------------------------------------------
# TestHelperInjection
# ---------------------------------------------------------------------------


class TestHelperInjection:
    def test_debug_captures_output(self, app_home: str) -> None:
        _write_script(app_home, DEBUG_SCRIPT)
        output: list[str] = []
        call_auth_module(app_home, "acquire_token", output)
        assert any("hello" in line for line in output)

    @patch("cli.helpers.auth.runtime.click.echo")
    def test_tell_user_captures_output(self, mock_echo: object, app_home: str) -> None:
        _write_script(app_home, TELL_USER_SCRIPT)
        output: list[str] = []
        call_auth_module(app_home, "acquire_token", output)
        assert any("msg" in line for line in output)

    @patch("cli.helpers.auth.runtime.click.prompt", return_value="user-input")
    def test_prompt_text_injected(self, mock_prompt: object, app_home: str) -> None:
        _write_script(app_home, PROMPT_TEXT_SCRIPT)
        result = call_auth_module(app_home, "acquire_token")
        assert result["headers"]["X-Value"] == "user-input"
