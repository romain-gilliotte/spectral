"""Tests for the auth CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
import pytest

from cli.commands.capture.types import CaptureBundle
from cli.main import cli


def _make_auth_mock_anthropic(script_response: str | None = None) -> MagicMock:
    """Create a mock anthropic module for auth analysis tests.

    If *script_response* is provided, the mock returns it as the LLM text.
    Otherwise returns a default script with ``acquire_token()``.
    """
    if script_response is None:
        script_response = (
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

    async def mock_create(**kwargs: Any) -> MagicMock:
        resp = MagicMock()
        content_block = MagicMock()
        content_block.type = "text"
        content_block.text = script_response
        resp.stop_reason = "end_turn"
        resp.content = [content_block]
        return resp

    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    mock_module = MagicMock()
    mock_module.AsyncAnthropic.return_value = mock_client
    return mock_module


class TestAuthAnalyze:
    def test_auth_analyze_writes_script(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """LLM returns script → file written to storage."""
        from cli.helpers.storage import auth_script_path, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        runner = CliRunner()
        mock_anthropic = _make_auth_mock_anthropic()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
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

        runner = CliRunner()
        mock_anthropic = _make_auth_mock_anthropic(script_response="NO_AUTH")
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
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
