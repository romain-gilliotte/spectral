"""Tests for cli.commands.auth.set."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner, Result

from cli.commands.auth.set import set_token
from cli.formats.mcp_tool import TokenState

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP = "myapp"
MODULE = "cli.commands.auth.set"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(
    args: list[str],
    *,
    input: str | None = None,
) -> tuple[MagicMock, MagicMock, Result]:
    """Invoke set_token via CliRunner and return (resolve_app, write_token, result)."""
    runner = CliRunner()
    with (
        patch(f"{MODULE}.resolve_app") as mock_resolve,
        patch(f"{MODULE}.write_token") as mock_write,
    ):
        result = runner.invoke(set_token, args, input=input, catch_exceptions=False)
        return mock_resolve, mock_write, result


def _written_token(mock_write: MagicMock) -> TokenState:
    """Extract the TokenState passed to write_token."""
    mock_write.assert_called_once()
    return mock_write.call_args[0][1]


# ---------------------------------------------------------------------------
# TestSetToken
# ---------------------------------------------------------------------------


class TestSetToken:
    def test_set_header(self) -> None:
        _, mock_write, result = _invoke([APP, "-H", "Authorization: Bearer tok"])
        assert result.exit_code == 0
        token = _written_token(mock_write)
        assert token.headers == {"Authorization": "Bearer tok"}
        assert token.body_params == {}

    def test_set_multiple_headers(self) -> None:
        _, mock_write, result = _invoke(
            [APP, "-H", "Authorization: Bearer tok", "-H", "X-Custom: val"]
        )
        assert result.exit_code == 0
        token = _written_token(mock_write)
        assert token.headers == {"Authorization": "Bearer tok", "X-Custom": "val"}

    def test_set_cookie(self) -> None:
        _, mock_write, result = _invoke([APP, "-c", "session=abc"])
        assert result.exit_code == 0
        token = _written_token(mock_write)
        assert token.headers == {"Cookie": "session=abc"}

    def test_set_multiple_cookies(self) -> None:
        _, mock_write, result = _invoke([APP, "-c", "a=1", "-c", "b=2"])
        assert result.exit_code == 0
        token = _written_token(mock_write)
        assert token.headers == {"Cookie": "a=1; b=2"}

    def test_set_body_param(self) -> None:
        _, mock_write, result = _invoke([APP, "-b", "token=xyz"])
        assert result.exit_code == 0
        token = _written_token(mock_write)
        assert token.body_params == {"token": "xyz"}
        assert token.headers == {}

    def test_invalid_header_format(self) -> None:
        _, mock_write, result = _invoke([APP, "-H", "bad"])
        assert result.exit_code == 1
        assert "Invalid header format" in result.output
        mock_write.assert_not_called()

    def test_invalid_body_param_format(self) -> None:
        _, mock_write, result = _invoke([APP, "-b", "bad"])
        assert result.exit_code == 1
        assert "Invalid body param format" in result.output
        mock_write.assert_not_called()

    def test_bearer_prompt_fallback(self) -> None:
        _, mock_write, result = _invoke([APP], input="mytoken\n")
        assert result.exit_code == 0
        token = _written_token(mock_write)
        assert token.headers == {"Authorization": "Bearer mytoken"}

    def test_bearer_prompt_strips_prefix(self) -> None:
        _, mock_write, result = _invoke([APP], input="Bearer mytoken\n")
        assert result.exit_code == 0
        token = _written_token(mock_write)
        assert token.headers == {"Authorization": "Bearer mytoken"}
        assert "Bearer Bearer" not in token.headers["Authorization"]
