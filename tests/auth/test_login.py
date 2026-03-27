# pyright: reportPrivateUsage=false
"""Tests for cli.commands.auth.login."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner, Result

from cli.commands.auth.login import login
from cli.helpers.auth._errors import AuthScriptError, AuthScriptNotFound

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP = "testapp"
MODULE = "cli.commands.auth.login"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(
    args: list[str],
    *,
    input: str | None = None,
) -> Result:
    """Invoke ``login`` via CliRunner with common mocks and return the result."""
    runner = CliRunner()
    with patch(f"{MODULE}.resolve_app"):
        return runner.invoke(login, args, input=input)


# ---------------------------------------------------------------------------
# TestLogin — happy path and error handling
# ---------------------------------------------------------------------------


class TestLogin:
    @patch(f"{MODULE}.acquire_auth")
    def test_success(self, mock_acquire: MagicMock) -> None:
        result = _invoke([APP])

        assert result.exit_code == 0
        assert "Login successful" in result.output
        mock_acquire.assert_called_once()

    @patch(f"{MODULE}.acquire_auth", side_effect=AuthScriptNotFound)
    def test_script_not_found(self, _mock_acquire: MagicMock) -> None:
        result = _invoke([APP])

        assert result.exit_code == 1
        assert "spectral auth analyze" in result.output

    @patch(f"{MODULE}.acquire_auth", side_effect=AuthScriptError)
    def test_script_error_directs_to_analyze(
        self, _mock_acquire: MagicMock
    ) -> None:
        result = _invoke([APP])

        assert result.exit_code == 1
        assert "spectral auth analyze" in result.output
