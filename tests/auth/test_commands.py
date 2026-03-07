"""Tests for the auth CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from click.testing import CliRunner
import pytest

from cli.commands.capture.types import CaptureBundle
from cli.helpers.llm._client import setup_client
from cli.main import cli

_DEFAULT_SCRIPT_RESPONSE = (
    '```python\nimport json\nimport urllib.request\n\n'
    'def acquire_token():\n'
    '    email = prompt_text("Email")\n'
    '    password = prompt_secret("Password")\n'
    '    data = json.dumps({"email": email, "password": password}).encode()\n'
    '    req = urllib.request.Request(\n'
    '        "https://api.example.com/auth/login",\n'
    '        data=data,\n'
    '        headers={"Content-Type": "application/json"},\n'
    '        method="POST",\n'
    '    )\n'
    '    resp = urllib.request.urlopen(req)\n'
    '    body = json.loads(resp.read())\n'
    '    token = body["access_token"]\n'
    '    return {"headers": {"Authorization": f"Bearer {token}"}, "expires_in": 3600}\n'
    '```'
)

# Base URL detection response (first LLM call in the auth pipeline)
_BASE_URL_RESPONSE = '{"base_url": "https://api.example.com"}'


def _make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    return resp


def _make_async_create(response_text: str):
    """Create an async mock that always returns the given text."""
    async def mock_create(**kwargs: Any) -> MagicMock:
        return _make_text_block(response_text)
    return mock_create


def _setup_auth_llm(script_response: str | None = None) -> None:
    """Set up a mock LLM client for auth analysis tests.

    Handles multiple LLM calls: first for base URL detection,
    then for auth script generation.
    """
    if script_response is None:
        script_response = _DEFAULT_SCRIPT_RESPONSE

    call_count = {"n": 0}
    final_script = script_response

    async def mock_create(**kwargs: Any) -> MagicMock:
        call_count["n"] += 1
        # First call: base URL detection
        if call_count["n"] == 1:
            return _make_text_block(_BASE_URL_RESPONSE)
        # Subsequent calls: auth script generation
        return _make_text_block(final_script)

    mock_client = MagicMock()
    mock_client.messages.create = mock_create
    setup_client(mock_client)


class TestAuthSet:
    def test_auth_set_single_header(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import load_token, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["auth", "set", "testapp", "-H", "Authorization: Bearer eyJ123"]
        )

        assert result.exit_code == 0, result.output
        assert "Token saved" in result.output

        token = load_token("testapp")
        assert token is not None
        assert token.headers == {"Authorization": "Bearer eyJ123"}

    def test_auth_set_cookies_only(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import load_token, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["auth", "set", "testapp", "-c", "a=1", "-c", "b=2"]
        )

        assert result.exit_code == 0, result.output
        token = load_token("testapp")
        assert token is not None
        assert token.headers == {"Cookie": "a=1; b=2"}

    def test_auth_set_headers_and_cookies(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import load_token, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "auth", "set", "testapp",
                "-H", "Authorization: Bearer tok",
                "-c", "sid=abc",
            ],
        )

        assert result.exit_code == 0, result.output
        token = load_token("testapp")
        assert token is not None
        assert token.headers == {"Authorization": "Bearer tok", "Cookie": "sid=abc"}

    def test_auth_set_interactive_fallback(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import load_token, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["auth", "set", "testapp"], input="my-secret-token\n"
        )

        assert result.exit_code == 0, result.output
        token = load_token("testapp")
        assert token is not None
        assert token.headers == {"Authorization": "Bearer my-secret-token"}

    def test_auth_set_interactive_strips_bearer_prefix(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import load_token, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["auth", "set", "testapp"], input="Bearer eyJ123\n"
        )

        assert result.exit_code == 0, result.output
        token = load_token("testapp")
        assert token is not None
        assert token.headers == {"Authorization": "Bearer eyJ123"}

    def test_auth_set_nonexistent_app(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "set", "nope", "-H", "X: Y"])

        assert result.exit_code != 0
        assert "not found" in result.output

    def test_auth_set_invalid_header_format(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["auth", "set", "testapp", "-H", "BadHeaderNoColon"]
        )

        assert result.exit_code != 0
        assert "Invalid header format" in result.output


_FAILING_SCRIPT = (
    'def acquire_token():\n'
    '    raise RuntimeError("connection refused")\n'
)

_FIXED_SCRIPT = (
    'import json\nimport urllib.request\n\n'
    'def acquire_token():\n'
    '    return {"headers": {"Authorization": "Bearer fixed-token"}}\n'
)

_FIXED_SCRIPT_RESPONSE = f'```python\n{_FIXED_SCRIPT}```'


class TestAuthLoginFix:
    def test_login_fix_on_failure(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Script fails → user accepts fix → LLM returns fixed script → login succeeds."""
        from cli.helpers.storage import auth_script_path, load_token, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        # Write the failing script
        script_path = auth_script_path("testapp")
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(_FAILING_SCRIPT)

        # Write app.json with base_url so detect_base_url uses cached value
        from cli.helpers.storage import update_app_meta
        update_app_meta("testapp", base_url="https://api.example.com")

        # Set up LLM mock — base URL is cached so only the fix call happens
        mock_client = MagicMock()
        mock_client.messages.create = _make_async_create(_FIXED_SCRIPT_RESPONSE)
        setup_client(mock_client)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["auth", "login", "testapp"],
            input="y\n",  # accept fix
        )

        assert result.exit_code == 0, result.output
        assert "Login failed" in result.output
        assert "Script updated" in result.output
        assert "Login successful" in result.output

        # Verify fixed script was written
        assert "Bearer fixed-token" in script_path.read_text()

        # Verify token was saved
        token = load_token("testapp")
        assert token is not None
        assert token.headers["Authorization"] == "Bearer fixed-token"

    def test_login_fix_declined(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Script fails → user declines fix → exit code 1, script unchanged."""
        from cli.helpers.storage import auth_script_path, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        # Write the failing script
        script_path = auth_script_path("testapp")
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(_FAILING_SCRIPT)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["auth", "login", "testapp"],
            input="n\n",  # decline fix
        )

        assert result.exit_code == 1
        assert "Login failed" in result.output

        # Script should be unchanged
        assert script_path.read_text() == _FAILING_SCRIPT


class TestAuthAnalyze:
    def test_auth_analyze_writes_script(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """LLM returns script → file written to storage."""
        from cli.helpers.storage import auth_script_path, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        _setup_auth_llm()
        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "analyze", "testapp"])

        assert result.exit_code == 0, result.output
        assert "Auth script written to" in result.output

        script_path = auth_script_path("testapp")
        assert script_path.exists()
        content = script_path.read_text()
        assert "def acquire_token" in content

    def test_auth_analyze_no_auth(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """LLM returns NO_AUTH → no script, info message shown."""
        from cli.helpers.storage import auth_script_path, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        _setup_auth_llm(script_response="NO_AUTH")
        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "analyze", "testapp"])

        assert result.exit_code == 0, result.output
        assert "No authentication mechanism detected" in result.output

        script_path = auth_script_path("testapp")
        assert not script_path.exists()

    def test_auth_analyze_nonexistent_app(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Nonexistent app → error exit code."""
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "analyze", "nope"])

        assert result.exit_code != 0
        assert "not found" in result.output
