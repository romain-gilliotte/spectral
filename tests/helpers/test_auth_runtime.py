"""Tests for auth runtime (token validation, acquire, refresh)."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from cli.formats.mcp_tool import TokenState
from cli.helpers.auth_runtime import (
    AuthError,
    acquire_auth,
    get_auth_headers,
    is_token_valid,
    load_auth_module,
    refresh_auth,
)
from cli.helpers.storage import (
    auth_script_path,
    ensure_app,
    write_token,
)


class TestIsTokenValid:
    def test_no_expiry(self) -> None:
        token = TokenState(headers={}, obtained_at=1000.0)
        assert is_token_valid(token) is True

    def test_valid_token(self) -> None:
        token = TokenState(
            headers={}, obtained_at=1000.0, expires_at=time.time() + 3600
        )
        assert is_token_valid(token) is True

    def test_expired_token(self) -> None:
        token = TokenState(
            headers={}, obtained_at=1000.0, expires_at=time.time() - 100
        )
        assert is_token_valid(token) is False


class TestGetAuthHeaders:
    def test_valid_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        write_token(
            "myapp",
            TokenState(
                headers={"Authorization": "Bearer tok123"},
                obtained_at=time.time(),
                expires_at=time.time() + 3600,
            ),
        )
        headers = get_auth_headers("myapp")
        assert headers == {"Authorization": "Bearer tok123"}

    def test_no_token_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        with pytest.raises(AuthError, match="No valid token"):
            get_auth_headers("myapp")

    def test_expired_no_refresh_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        write_token(
            "myapp",
            TokenState(
                headers={"Authorization": "Bearer old"},
                obtained_at=1000.0,
                expires_at=time.time() - 100,
            ),
        )
        with pytest.raises(AuthError, match="No valid token"):
            get_auth_headers("myapp")

    def test_expired_with_auto_refresh(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")

        # Write an expired token with a refresh token
        write_token(
            "myapp",
            TokenState(
                headers={"Authorization": "Bearer old"},
                refresh_token="rt_abc",
                obtained_at=1000.0,
                expires_at=time.time() - 100,
            ),
        )

        # Write an auth script with refresh_token function
        script = auth_script_path("myapp")
        script.write_text(
            "def refresh_token(current_refresh_token):\n"
            '    return {"headers": {"Authorization": "Bearer refreshed"}, "expires_in": 3600}\n'
        )

        headers = get_auth_headers("myapp")
        assert headers == {"Authorization": "Bearer refreshed"}


class TestLoadAuthModule:
    def test_load_with_prompt_utilities(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        script = auth_script_path("myapp")
        script.write_text(
            "def acquire_token():\n"
            "    return {'headers': {'X-Token': 'test'}}\n"
        )
        mod = load_auth_module("myapp")
        assert hasattr(mod, "acquire_token")
        assert hasattr(mod, "prompt_text")
        assert hasattr(mod, "prompt_secret")

    def test_load_missing_script(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        with pytest.raises(AuthError, match="Auth script not found"):
            load_auth_module("myapp")


class TestAcquireAuth:
    def test_acquire(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        script = auth_script_path("myapp")
        script.write_text(
            "def acquire_token():\n"
            "    return {'headers': {'Authorization': 'Bearer new'}, 'expires_in': 1800}\n"
        )
        token = acquire_auth("myapp")
        assert token.headers == {"Authorization": "Bearer new"}
        assert token.expires_at is not None

    def test_acquire_no_function(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        script = auth_script_path("myapp")
        script.write_text("# no acquire_token function\n")
        with pytest.raises(AuthError, match="does not define acquire_token"):
            acquire_auth("myapp")


class TestRefreshAuth:
    def test_refresh(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        script = auth_script_path("myapp")
        script.write_text(
            "def refresh_token(current_refresh_token):\n"
            "    return {'headers': {'Authorization': 'Bearer refreshed'}, 'refresh_token': 'rt_new'}\n"
        )
        token = TokenState(
            headers={"Authorization": "Bearer old"},
            refresh_token="rt_old",
            obtained_at=1000.0,
        )
        new_token = refresh_auth("myapp", token)
        assert new_token.headers == {"Authorization": "Bearer refreshed"}
        assert new_token.refresh_token == "rt_new"

    def test_refresh_no_function(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        script = auth_script_path("myapp")
        script.write_text("def acquire_token(): pass\n")
        token = TokenState(headers={}, refresh_token="rt", obtained_at=1000.0)
        with pytest.raises(AuthError, match="does not define refresh_token"):
            refresh_auth("myapp", token)
