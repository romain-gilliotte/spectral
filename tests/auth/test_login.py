# pyright: reportPrivateUsage=false
"""Tests for cli.commands.auth.login."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner, Result

from cli.commands.auth.login import login
from cli.helpers.auth.errors import (
    AuthScriptError,
    AuthScriptInvalid,
    AuthScriptNotFound,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP = "testapp"
MODULE = "cli.commands.auth.login"
FIXED_SCRIPT = "def acquire_token():\n    return {'headers': {'Authorization': 'Bearer fixed'}}\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(
    args: list[str],
    *,
    input: str | None = None,
) -> Result:
    """Invoke ``login`` via CliRunner with common mocks and return the result.

    Mocks resolve_app and init_debug for all invocations.
    """
    runner = CliRunner()
    with (
        patch(f"{MODULE}.resolve_app"),
        patch(f"{MODULE}.init_debug"),
    ):
        return runner.invoke(login, args, input=input)


# ---------------------------------------------------------------------------
# TestLogin — happy path and top-level error handling
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

    @patch(f"{MODULE}.click.confirm", return_value=False)
    @patch(f"{MODULE}.acquire_auth", side_effect=AuthScriptError)
    def test_script_error_user_declines_fix(
        self, _mock_acquire: MagicMock, _mock_confirm: MagicMock
    ) -> None:
        result = _invoke([APP])

        assert result.exit_code == 1
        assert "spectral auth analyze" in result.output


# ---------------------------------------------------------------------------
# TestAttemptFixAndRetry — LLM fix loop
# ---------------------------------------------------------------------------


class TestAttemptFixAndRetry:
    """Tests that exercise the fix-and-retry loop inside _attempt_fix_and_retry."""

    def _invoke_with_fix_mocks(
        self,
        *,
        acquire_side_effect: list[object],
        extract_side_effect: list[object],
        tmp_path: Path,
    ) -> Result:
        """Set up all mocks needed for the fix loop and invoke the command.

        *acquire_side_effect* controls successive acquire_auth calls.
        *extract_side_effect* controls successive extract_script calls.
        """
        script_path = tmp_path / "auth_acquire.py"
        script_path.write_text("# placeholder")

        mock_conversation = MagicMock()
        mock_conversation.ask_text.return_value = "```python\n...\n```"

        runner = CliRunner()
        with (
            patch(f"{MODULE}.resolve_app"),
            patch(f"{MODULE}.init_debug"),
            patch(f"{MODULE}.acquire_auth", side_effect=acquire_side_effect),
            patch(f"{MODULE}.click.confirm", return_value=True),
            patch(f"{MODULE}.load_app_bundle", return_value=MagicMock()),
            patch(f"{MODULE}.build_timeline", return_value=""),
            patch(f"{MODULE}.get_auth_instructions", return_value=""),
            patch(f"{MODULE}.Conversation", return_value=mock_conversation),
            patch(f"{MODULE}.auth_script_path", return_value=script_path),
            patch(f"{MODULE}.render", return_value="prompt text"),
            patch(f"{MODULE}.extract_script", side_effect=extract_side_effect),
        ):
            return runner.invoke(login, [APP])

    def test_fix_succeeds_on_first_attempt(self, tmp_path: Path) -> None:
        result = self._invoke_with_fix_mocks(
            acquire_side_effect=[AuthScriptError, None],
            extract_side_effect=[FIXED_SCRIPT],
            tmp_path=tmp_path,
        )

        assert result.exit_code == 0
        assert "Login successful" in result.output

    def test_fix_exhausts_attempts(self, tmp_path: Path) -> None:
        result = self._invoke_with_fix_mocks(
            acquire_side_effect=[AuthScriptError],
            extract_side_effect=[
                AuthScriptInvalid("bad 1"),
                AuthScriptInvalid("bad 2"),
                AuthScriptInvalid("bad 3"),
                AuthScriptInvalid("bad 4"),
                AuthScriptInvalid("bad 5"),
            ],
            tmp_path=tmp_path,
        )

        assert result.exit_code == 1
        assert "5 fix attempts" in result.output

    def test_fix_no_auth_detected(self, tmp_path: Path) -> None:
        result = self._invoke_with_fix_mocks(
            acquire_side_effect=[AuthScriptError],
            extract_side_effect=[None],
            tmp_path=tmp_path,
        )

        assert result.exit_code == 1
        assert "No auth mechanism found" in result.output
