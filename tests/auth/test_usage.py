# pyright: reportPrivateUsage=false
"""Tests for cli/helpers/auth/usage.py."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from cli.helpers.auth.errors import AuthError, AuthScriptError
from cli.helpers.auth.usage import (
    _is_token_valid,
    _result_to_token_state,
    acquire_auth,
    get_auth,
    refresh_auth,
)
from tests.auth.conftest import make_token

FIXED_NOW = 1_700_000_000.0
MODULE = "cli.helpers.auth.usage"


# ---------------------------------------------------------------------------
# get_auth
# ---------------------------------------------------------------------------


class TestGetAuth:
    @patch(f"{MODULE}.load_token")
    def test_valid_token_returned_directly(self, mock_load: object) -> None:
        token = make_token(expires_at=time.time() + 3600)
        mock_load.return_value = token  # type: ignore[union-attr]

        result = get_auth("myapp")

        assert result is token

    @patch(f"{MODULE}.write_token")
    @patch(f"{MODULE}.call_auth_module")
    @patch(f"{MODULE}.load_token")
    def test_expired_token_with_refresh_triggers_refresh(
        self, mock_load: object, mock_call: object, mock_write: object
    ) -> None:
        token = make_token(
            expires_at=time.time() - 100,
            refresh_token="rt_old",
        )
        mock_load.return_value = token  # type: ignore[union-attr]
        mock_call.return_value = {  # type: ignore[union-attr]
            "headers": {"Authorization": "Bearer new"},
            "refresh_token": "rt_new",
            "expires_in": 3600,
        }

        result = get_auth("myapp")

        assert result.headers == {"Authorization": "Bearer new"}
        mock_call.assert_called_once()  # type: ignore[union-attr]
        mock_write.assert_called_once()  # type: ignore[union-attr]

    @patch(f"{MODULE}.load_token")
    def test_expired_token_without_refresh_raises(self, mock_load: object) -> None:
        token = make_token(expires_at=time.time() - 100, refresh_token=None)
        mock_load.return_value = token  # type: ignore[union-attr]

        with pytest.raises(AuthError, match="No valid token"):
            get_auth("myapp")

    @patch(f"{MODULE}.load_token")
    def test_no_token_raises(self, mock_load: object) -> None:
        mock_load.return_value = None  # type: ignore[union-attr]

        with pytest.raises(AuthError, match="No valid token"):
            get_auth("myapp")

    @patch(f"{MODULE}.call_auth_module", side_effect=AuthScriptError)
    @patch(f"{MODULE}.load_token")
    def test_refresh_failure_raises(
        self, mock_load: object, _mock_call: object
    ) -> None:
        token = make_token(expires_at=time.time() - 100, refresh_token="rt_old")
        mock_load.return_value = token  # type: ignore[union-attr]

        with pytest.raises(AuthError, match="No valid token"):
            get_auth("myapp")


# ---------------------------------------------------------------------------
# refresh_auth
# ---------------------------------------------------------------------------


class TestRefreshAuth:
    @patch(f"{MODULE}.write_token")
    @patch(f"{MODULE}.call_auth_module")
    def test_calls_module_and_writes(
        self, mock_call: object, mock_write: object
    ) -> None:
        mock_call.return_value = {  # type: ignore[union-attr]
            "headers": {"Authorization": "Bearer refreshed"},
            "refresh_token": "rt_new",
            "expires_in": 7200,
        }
        token = make_token(refresh_token="rt_old")

        result = refresh_auth("myapp", token)

        assert result.headers == {"Authorization": "Bearer refreshed"}
        assert result.refresh_token == "rt_new"
        mock_call.assert_called_once_with(  # type: ignore[union-attr]
            "myapp", "refresh_token", None, "rt_old"
        )
        mock_write.assert_called_once_with("myapp", result)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# acquire_auth
# ---------------------------------------------------------------------------


class TestAcquireAuth:
    @patch(f"{MODULE}.write_token")
    @patch(f"{MODULE}.call_auth_module")
    def test_calls_module_and_writes(
        self, mock_call: object, mock_write: object
    ) -> None:
        mock_call.return_value = {  # type: ignore[union-attr]
            "headers": {"Authorization": "Bearer acquired"},
            "expires_in": 1800,
        }

        result = acquire_auth("myapp")

        assert result.headers == {"Authorization": "Bearer acquired"}
        mock_call.assert_called_once_with("myapp", "acquire_token", None)  # type: ignore[union-attr]
        mock_write.assert_called_once_with("myapp", result)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# _is_token_valid
# ---------------------------------------------------------------------------


class TestIsTokenValid:
    def test_no_expiry_is_valid(self) -> None:
        token = make_token(expires_at=None)
        assert _is_token_valid(token) is True

    def test_future_expiry_is_valid(self) -> None:
        token = make_token(expires_at=time.time() + 3600)
        assert _is_token_valid(token) is True

    def test_past_expiry_is_invalid(self) -> None:
        token = make_token(expires_at=time.time() - 100)
        assert _is_token_valid(token) is False


# ---------------------------------------------------------------------------
# _result_to_token_state
# ---------------------------------------------------------------------------


class TestResultToTokenState:
    @patch(f"{MODULE}.time")
    def test_basic_headers(self, mock_time: object) -> None:
        mock_time.time.return_value = FIXED_NOW  # type: ignore[union-attr]

        result = _result_to_token_state({"headers": {"X-Key": "abc"}})

        assert result.headers == {"X-Key": "abc"}
        assert result.body_params == {}
        assert result.refresh_token is None
        assert result.expires_at is None
        assert result.obtained_at == FIXED_NOW

    @patch(f"{MODULE}.time")
    def test_with_expires_in(self, mock_time: object) -> None:
        mock_time.time.return_value = FIXED_NOW  # type: ignore[union-attr]

        result = _result_to_token_state(
            {"headers": {"Authorization": "Bearer t"}, "expires_in": 3600}
        )

        assert result.expires_at == FIXED_NOW + 3600

    @patch(f"{MODULE}.time")
    def test_with_refresh_token(self, mock_time: object) -> None:
        mock_time.time.return_value = FIXED_NOW  # type: ignore[union-attr]

        result = _result_to_token_state(
            {"headers": {}, "refresh_token": "rt_abc"}
        )

        assert result.refresh_token == "rt_abc"

    @patch(f"{MODULE}.time")
    def test_empty_result(self, mock_time: object) -> None:
        mock_time.time.return_value = FIXED_NOW  # type: ignore[union-attr]

        result = _result_to_token_state({})

        assert result.headers == {}
        assert result.body_params == {}
        assert result.refresh_token is None
        assert result.expires_at is None

    @patch(f"{MODULE}.time")
    def test_body_params_preserved(self, mock_time: object) -> None:
        mock_time.time.return_value = FIXED_NOW  # type: ignore[union-attr]

        result = _result_to_token_state(
            {"headers": {}, "body_params": {"token": "xyz"}}
        )

        assert result.body_params == {"token": "xyz"}
