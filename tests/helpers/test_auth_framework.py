"""Tests for cli.helpers.auth_framework."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import time
from typing import IO, Any
from unittest.mock import patch

from cli.helpers.auth_framework import AUTH_FRAMEWORK_CODE, generate_auth_script

# ---------------------------------------------------------------------------
# Helpers: execute the framework code in an isolated namespace
# ---------------------------------------------------------------------------

def _exec_framework() -> dict[str, Any]:
    """Execute AUTH_FRAMEWORK_CODE in a fresh namespace and return it."""
    ns: dict[str, Any] = {}
    exec(AUTH_FRAMEWORK_CODE, ns)
    return ns


def _make_jwt(payload: dict[str, Any]) -> str:
    """Build a fake unsigned JWT with the given payload."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


# ---------------------------------------------------------------------------
# TokenCache
# ---------------------------------------------------------------------------

class TestTokenCache:
    def test_read_write_roundtrip(self, tmp_path: Path) -> None:
        ns = _exec_framework()
        cache = ns["TokenCache"]("test-api")
        cache._path = tmp_path / "token.json"

        assert cache.read() is None  # no file yet

        cache.write({"token": "abc", "acquired_at": 12345})
        result = cache.read()
        assert result is not None
        assert result["token"] == "abc"
        assert result["acquired_at"] == 12345

    def test_read_missing_directory(self, tmp_path: Path) -> None:
        ns = _exec_framework()
        cache = ns["TokenCache"]("test-api")
        cache._path = tmp_path / "nonexistent" / "deep" / "token.json"

        assert cache.read() is None

    def test_read_corrupt_file(self, tmp_path: Path) -> None:
        ns = _exec_framework()
        cache = ns["TokenCache"]("test-api")
        cache._path = tmp_path / "token.json"
        cache._path.write_text("not json{{{")

        assert cache.read() is None

    def test_write_creates_directory(self, tmp_path: Path) -> None:
        ns = _exec_framework()
        cache = ns["TokenCache"]("test-api")
        cache._path = tmp_path / "new" / "dir" / "token.json"

        cache.write({"token": "xyz"})
        assert cache._path.exists()
        assert json.loads(cache._path.read_text())["token"] == "xyz"

    def test_clear_removes_file(self, tmp_path: Path) -> None:
        ns = _exec_framework()
        cache = ns["TokenCache"]("test-api")
        cache._path = tmp_path / "token.json"

        cache.write({"token": "del"})
        assert cache._path.exists()

        cache.clear()
        assert not cache._path.exists()

    def test_clear_no_file(self, tmp_path: Path) -> None:
        """clear() should not raise when file doesn't exist."""
        ns = _exec_framework()
        cache = ns["TokenCache"]("test-api")
        cache._path = tmp_path / "nonexistent.json"

        cache.clear()  # should not raise


# ---------------------------------------------------------------------------
# is_token_expired
# ---------------------------------------------------------------------------

class TestIsTokenExpired:
    def test_jwt_not_expired(self) -> None:
        ns = _exec_framework()
        future_exp = int(time.time()) + 3600
        token = _make_jwt({"exp": future_exp})
        cached = {"token": token, "acquired_at": time.time()}
        assert ns["is_token_expired"](cached) is False

    def test_jwt_expired(self) -> None:
        ns = _exec_framework()
        past_exp = int(time.time()) - 10
        token = _make_jwt({"exp": past_exp})
        cached = {"token": token, "acquired_at": time.time()}
        assert ns["is_token_expired"](cached) is True

    def test_ttl_fallback_not_expired(self) -> None:
        ns = _exec_framework()
        cached = {
            "token": "opaque-token",
            "acquired_at": time.time() - 100,
            "expires_in": 3600,
        }
        assert ns["is_token_expired"](cached) is False

    def test_ttl_fallback_expired(self) -> None:
        ns = _exec_framework()
        cached = {
            "token": "opaque-token",
            "acquired_at": time.time() - 7200,
            "expires_in": 3600,
        }
        assert ns["is_token_expired"](cached) is True

    def test_default_ttl_1h(self) -> None:
        """Without expires_in, default TTL is 1h."""
        ns = _exec_framework()
        cached = {
            "token": "opaque",
            "acquired_at": time.time() - 3601,
        }
        assert ns["is_token_expired"](cached) is True

    def test_no_acquired_at(self) -> None:
        """Missing acquired_at means expired."""
        ns = _exec_framework()
        cached = {"token": "opaque"}
        assert ns["is_token_expired"](cached) is True


# ---------------------------------------------------------------------------
# prompt_credentials
# ---------------------------------------------------------------------------

class TestPromptCredentials:
    def test_basic_prompting(self, tmp_path: Path) -> None:
        ns = _exec_framework()
        tty_input = tmp_path / "tty_in"
        tty_input.write_text("user@example.com\n")
        tty_out_path = tmp_path / "tty_out"

        _real_open = open  # capture before patching

        def mock_open(path: str, mode: str = "r") -> IO[Any]:
            if path == "/dev/tty" and mode == "r":
                return _real_open(tty_input, "r")
            if path == "/dev/tty" and mode == "w":
                return _real_open(tty_out_path, "a")
            return _real_open(path, mode)

        with patch("builtins.open", side_effect=mock_open):
            result: dict[str, str] = ns["prompt_credentials"]({"email": "Your email"})

        assert result["email"] == "user@example.com"

    def test_password_field_uses_getpass(self, tmp_path: Path) -> None:
        ns = _exec_framework()
        tty_input = tmp_path / "tty_in"
        tty_input.write_text("")
        tty_out_path = tmp_path / "tty_out"

        _real_open = open

        def mock_open(path: str, mode: str = "r") -> IO[Any]:
            if path == "/dev/tty" and mode == "r":
                return _real_open(tty_input, "r")
            if path == "/dev/tty" and mode == "w":
                return _real_open(tty_out_path, "a")
            return _real_open(path, mode)

        with patch("builtins.open", side_effect=mock_open), \
             patch("getpass.getpass", return_value="s3cret"):
            result: dict[str, str] = ns["prompt_credentials"]({"password": "Your password"})

        assert result["password"] == "s3cret"


# ---------------------------------------------------------------------------
# get_token
# ---------------------------------------------------------------------------

class TestGetToken:
    def test_cached_valid_token(self, tmp_path: Path) -> None:
        ns = _exec_framework()
        cache = ns["TokenCache"]("test-api")
        cache._path = tmp_path / "token.json"

        future_exp = int(time.time()) + 3600
        token = _make_jwt({"exp": future_exp})
        cache.write({"token": token, "acquired_at": time.time()})

        result: str = ns["get_token"](cache, {"email": "Your email"})
        assert result == token

    def test_expired_token_reacquires(self, tmp_path: Path) -> None:
        ns = _exec_framework()
        cache: Any = ns["TokenCache"]("test-api")
        cache._path = tmp_path / "token.json"

        past_exp = int(time.time()) - 10
        old_token = _make_jwt({"exp": past_exp})
        cache.write({"token": old_token, "acquired_at": time.time() - 7200})

        # Mock acquire_token in the namespace
        def mock_acquire(creds: dict[str, str]) -> dict[str, str]:
            return {"token": "new-token", "expires_in": "3600"}

        ns["acquire_token"] = mock_acquire

        def mock_prompt(fields: dict[str, str]) -> dict[str, str]:
            return {"email": "test@test.com"}

        ns["prompt_credentials"] = mock_prompt
        result: str = ns["get_token"](cache, {"email": "Your email"})
        assert result == "new-token"

    def test_refresh_token_used_when_available(self, tmp_path: Path) -> None:
        ns = _exec_framework()
        cache: Any = ns["TokenCache"]("test-api")
        cache._path = tmp_path / "token.json"

        past_exp = int(time.time()) - 10
        old_token = _make_jwt({"exp": past_exp})
        cache.write({
            "token": old_token,
            "refresh_token": "refresh-abc",
            "acquired_at": time.time() - 7200,
        })

        def mock_refresh(rt: str) -> dict[str, str]:
            return {"token": "refreshed-token"}

        ns["refresh_token"] = mock_refresh
        result: str = ns["get_token"](cache, {"email": "Your email"})
        assert result == "refreshed-token"

    def test_refresh_failure_falls_back_to_acquire(self, tmp_path: Path) -> None:
        ns = _exec_framework()
        cache: Any = ns["TokenCache"]("test-api")
        cache._path = tmp_path / "token.json"

        past_exp = int(time.time()) - 10
        old_token = _make_jwt({"exp": past_exp})
        cache.write({
            "token": old_token,
            "refresh_token": "refresh-abc",
            "acquired_at": time.time() - 7200,
        })

        def bad_refresh(rt: str) -> dict[str, str]:
            raise Exception("refresh failed")

        def mock_acquire(creds: dict[str, str]) -> dict[str, str]:
            return {"token": "acquired-token"}

        def mock_prompt(fields: dict[str, str]) -> dict[str, str]:
            return {"email": "test"}

        ns["refresh_token"] = bad_refresh
        ns["acquire_token"] = mock_acquire
        ns["prompt_credentials"] = mock_prompt

        result: str = ns["get_token"](cache, {"email": "Your email"})
        assert result == "acquired-token"


# ---------------------------------------------------------------------------
# restish_mode / token_mode
# ---------------------------------------------------------------------------

class TestRestishMode:
    def test_injects_auth_header(self, tmp_path: Path) -> None:
        ns = _exec_framework()

        # Set up module globals
        ns["_API_NAME"] = "test-api"
        ns["_CREDENTIAL_FIELDS"] = {}

        # Mock cache to return a valid token
        cache_path = tmp_path / "token.json"
        future_exp = int(time.time()) + 3600
        token = _make_jwt({"exp": future_exp})
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "token": token, "acquired_at": time.time()
        }))

        # Patch TokenCache to use our tmp_path
        OrigCache: Any = ns["TokenCache"]
        class MockCache(OrigCache):  # type: ignore[misc]
            def __init__(self, api_name: str) -> None:
                super().__init__(api_name)  # pyright: ignore[reportUnknownMemberType]
                self._path = cache_path

        ns["TokenCache"] = MockCache

        request_json = json.dumps({"method": "GET", "uri": "/test", "headers": {}})

        import io
        with patch("sys.stdin", io.StringIO(request_json)), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            ns["restish_mode"]("Authorization", "Bearer")
            output = mock_out.getvalue()

        result: dict[str, Any] = json.loads(output)
        assert "Authorization" in result["headers"]
        auth_value: list[str] = result["headers"]["Authorization"]
        assert isinstance(auth_value, list)
        assert auth_value[0].startswith("Bearer ")


class TestTokenMode:
    def test_prints_token(self, tmp_path: Path) -> None:
        ns = _exec_framework()

        ns["_API_NAME"] = "test-api"
        ns["_CREDENTIAL_FIELDS"] = {}

        cache_path = tmp_path / "token.json"
        future_exp = int(time.time()) + 3600
        token = _make_jwt({"exp": future_exp})
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "token": token, "acquired_at": time.time()
        }))

        OrigCache: Any = ns["TokenCache"]
        class MockCache(OrigCache):  # type: ignore[misc]
            def __init__(self, api_name: str) -> None:
                super().__init__(api_name)  # pyright: ignore[reportUnknownMemberType]
                self._path = cache_path

        ns["TokenCache"] = MockCache

        import io
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            ns["token_mode"]()
            output = mock_out.getvalue()

        assert output == token


# ---------------------------------------------------------------------------
# generate_auth_script
# ---------------------------------------------------------------------------

class TestGenerateAuthScript:
    def test_produces_valid_python(self) -> None:
        acquire_source = (
            "import urllib.request\n"
            "import json\n\n"
            "def acquire_token(credentials):\n"
            "    return {'token': 'test'}\n"
        )
        script = generate_auth_script(
            acquire_source=acquire_source,
            api_name="my-api",
            credential_fields={"email": "Your email", "password": "Your password"},
            token_header="Authorization",
            token_prefix="Bearer",
        )
        # Must compile without errors
        compile(script, "<test>", "exec")

    def test_contains_shebang(self) -> None:
        script = generate_auth_script(
            acquire_source="def acquire_token(creds):\n    return {'token': 'x'}\n",
            api_name="test-api",
            credential_fields={},
        )
        assert script.startswith("#!/usr/bin/env python3")

    def test_contains_acquire_function(self) -> None:
        source = "def acquire_token(creds):\n    return {'token': 'x'}\n"
        script = generate_auth_script(
            acquire_source=source,
            api_name="test-api",
            credential_fields={},
        )
        assert "def acquire_token" in script

    def test_contains_framework_code(self) -> None:
        script = generate_auth_script(
            acquire_source="def acquire_token(creds):\n    return {'token': 'x'}\n",
            api_name="test-api",
            credential_fields={},
        )
        assert "class TokenCache" in script
        assert "def main(" in script
        assert "def restish_mode(" in script
        assert "def token_mode(" in script

    def test_contains_entry_point(self) -> None:
        script = generate_auth_script(
            acquire_source="def acquire_token(creds):\n    return {'token': 'x'}\n",
            api_name="test-api",
            credential_fields={"user": "Username"},
        )
        assert 'if __name__ == "__main__"' in script
        assert "'test-api'" in script
        assert "'user'" in script

    def test_credential_fields_embedded(self) -> None:
        script = generate_auth_script(
            acquire_source="def acquire_token(creds):\n    return {'token': 'x'}\n",
            api_name="test-api",
            credential_fields={"email": "Your email", "password": "Your password"},
        )
        assert "'email'" in script
        assert "'password'" in script

    def test_restish_flag_documented(self) -> None:
        script = generate_auth_script(
            acquire_source="def acquire_token(creds):\n    return {'token': 'x'}\n",
            api_name="test-api",
            credential_fields={},
        )
        assert "--restish" in script
