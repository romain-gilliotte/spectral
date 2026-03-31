"""Tests for cli.commands.auth.{analyze_acquire,logout,refresh}."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from cli.commands.auth.analyze_acquire import analyze_acquire
from cli.commands.auth.logout import logout
from cli.helpers.auth._errors import AuthScriptInvalid

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP = "testapp"
ANALYZE_MODULE = "cli.commands.auth.analyze_acquire"
LOGOUT_MODULE = "cli.commands.auth.logout"
FAKE_SCRIPT = "def acquire_token():\n    return {}\n"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_bundle() -> MagicMock:
    bundle = MagicMock()
    bundle.traces = []
    return bundle


def _analyze_patches(tmp_path: Path) -> dict[str, MagicMock]:
    """Build a dict of patch targets for analyze_acquire, keyed by short name."""
    script_path = tmp_path / "auth_acquire.py"
    mocks: dict[str, MagicMock] = {}
    mocks["resolve_app"] = MagicMock()
    mocks["load_app_bundle"] = MagicMock(return_value=_mock_bundle())
    mocks["init_debug"] = MagicMock()
    mocks["build_timeline"] = MagicMock(return_value="timeline")
    mocks["get_acquire_instructions"] = MagicMock(return_value="instructions")
    mocks["auth_script_path"] = MagicMock(return_value=script_path)

    conv_instance = MagicMock()
    conv_instance.ask_text.return_value = "llm output"
    mocks["Conversation"] = MagicMock(return_value=conv_instance)
    mocks["conv_instance"] = conv_instance
    return mocks


# ---------------------------------------------------------------------------
# TestAnalyzeAcquire
# ---------------------------------------------------------------------------


class TestAnalyzeAcquire:
    def test_auth_detected_writes_script(self, tmp_path: Path) -> None:
        mocks = _analyze_patches(tmp_path)
        script_path: Path = mocks["auth_script_path"].return_value

        with (
            patch(f"{ANALYZE_MODULE}.resolve_app", mocks["resolve_app"]),
            patch(f"{ANALYZE_MODULE}.load_app_bundle", mocks["load_app_bundle"]),
            patch(f"{ANALYZE_MODULE}.init_debug", mocks["init_debug"]),
            patch(f"{ANALYZE_MODULE}.build_timeline", mocks["build_timeline"]),
            patch(f"{ANALYZE_MODULE}.get_acquire_instructions", mocks["get_acquire_instructions"]),
            patch(f"{ANALYZE_MODULE}.auth_script_path", mocks["auth_script_path"]),
            patch(f"{ANALYZE_MODULE}.Conversation", mocks["Conversation"]),
            patch(f"{ANALYZE_MODULE}.extract_script", return_value=FAKE_SCRIPT) as mock_extract,
        ):
            result = CliRunner().invoke(analyze_acquire, [APP], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Acquire script written" in result.output
        assert script_path.read_text() == FAKE_SCRIPT
        mock_extract.assert_called_once_with("llm output")

    def test_no_auth_detected(self, tmp_path: Path) -> None:
        mocks = _analyze_patches(tmp_path)

        with (
            patch(f"{ANALYZE_MODULE}.resolve_app", mocks["resolve_app"]),
            patch(f"{ANALYZE_MODULE}.load_app_bundle", mocks["load_app_bundle"]),
            patch(f"{ANALYZE_MODULE}.init_debug", mocks["init_debug"]),
            patch(f"{ANALYZE_MODULE}.build_timeline", mocks["build_timeline"]),
            patch(f"{ANALYZE_MODULE}.get_acquire_instructions", mocks["get_acquire_instructions"]),
            patch(f"{ANALYZE_MODULE}.Conversation", mocks["Conversation"]),
            patch(f"{ANALYZE_MODULE}.extract_script", return_value=None),
        ):
            result = CliRunner().invoke(analyze_acquire, [APP], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No authentication mechanism detected" in result.output

    def test_invalid_script(self, tmp_path: Path) -> None:
        mocks = _analyze_patches(tmp_path)

        with (
            patch(f"{ANALYZE_MODULE}.resolve_app", mocks["resolve_app"]),
            patch(f"{ANALYZE_MODULE}.load_app_bundle", mocks["load_app_bundle"]),
            patch(f"{ANALYZE_MODULE}.init_debug", mocks["init_debug"]),
            patch(f"{ANALYZE_MODULE}.build_timeline", mocks["build_timeline"]),
            patch(f"{ANALYZE_MODULE}.get_acquire_instructions", mocks["get_acquire_instructions"]),
            patch(f"{ANALYZE_MODULE}.Conversation", mocks["Conversation"]),
            patch(f"{ANALYZE_MODULE}.extract_script", side_effect=AuthScriptInvalid()),
        ):
            result = CliRunner().invoke(analyze_acquire, [APP], catch_exceptions=False)

        assert "No working auth script produced" in result.output


# ---------------------------------------------------------------------------
# TestLogout
# ---------------------------------------------------------------------------


class TestLogout:
    def test_token_deleted(self) -> None:
        with (
            patch(f"{LOGOUT_MODULE}.resolve_app") as mock_resolve,
            patch(f"{LOGOUT_MODULE}.delete_token", return_value=True),
        ):
            result = CliRunner().invoke(logout, [APP], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Logged out" in result.output
        mock_resolve.assert_called_once_with(APP)

    def test_no_token(self) -> None:
        with (
            patch(f"{LOGOUT_MODULE}.resolve_app"),
            patch(f"{LOGOUT_MODULE}.delete_token", return_value=False),
        ):
            result = CliRunner().invoke(logout, [APP], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No token found" in result.output


