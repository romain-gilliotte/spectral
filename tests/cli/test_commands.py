"""Tests for the CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
import pytest
import yaml

from cli.commands.capture.loader import write_bundle
from cli.commands.capture.types import CaptureBundle
from cli.formats.capture_bundle import CaptureStats
from cli.main import cli


def _make_mock_anthropic_module() -> MagicMock:
    """Create a mock anthropic module with AsyncAnthropic client."""

    # Standard LLM responses for the pipeline
    groups_response = json.dumps(
        [
            {
                "method": "GET",
                "pattern": "/api/users",
                "urls": ["https://api.example.com/api/users"],
            },
            {
                "method": "GET",
                "pattern": "/api/users/{user_id}/orders",
                "urls": [
                    "https://api.example.com/api/users/123/orders",
                    "https://api.example.com/api/users/456/orders",
                ],
            },
            {
                "method": "POST",
                "pattern": "/api/orders",
                "urls": ["https://api.example.com/api/orders"],
            },
        ]
    )

    auth_response = json.dumps(
        {
            "type": "bearer_token",
            "token_header": "Authorization",
            "token_prefix": "Bearer",
            "business_process": "Token auth",
            "user_journey": ["Login"],
            "obtain_flow": "login_form",
        }
    )

    enrich_response = json.dumps(
        {
            "description": "test purpose",
            "field_descriptions": {},
            "response_details": {},
            "discovery_notes": None,
        }
    )

    base_url_response = json.dumps({"base_url": "https://api.example.com"})

    async def mock_create(**kwargs: object) -> MagicMock:
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_response.stop_reason = "end_turn"
        messages_raw = kwargs.get("messages")
        messages = cast(list[dict[str, str]], messages_raw if isinstance(messages_raw, list) else [])
        first_msg = messages[0] if len(messages) > 0 else {}
        msg: str = str(first_msg.get("content", ""))
        if "base URL" in msg and "business API" in msg:
            mock_content.text = base_url_response
        elif "Group these observed URLs" in msg:
            mock_content.text = groups_response
        elif "authentication" in msg:
            mock_content.text = auth_response
        elif "single API endpoint" in msg:
            mock_content.text = enrich_response
        else:
            # Fallback
            mock_content.text = enrich_response
        mock_response.content = [mock_content]
        return mock_response

    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    mock_module = MagicMock()
    mock_module.AsyncAnthropic.return_value = mock_client
    return mock_module


class TestAnalyzeCommand:
    def test_analyze_basic(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test the analyze command with mocked LLM."""
        from cli.helpers.storage import store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        output_path = tmp_path / "spec.yaml"
        runner = CliRunner()

        mock_anthropic = _make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = runner.invoke(
                cli,
                ["analyze", "testapp", "-o", str(output_path)],
            )

        assert result.exit_code == 0, result.output
        assert output_path.exists()

        openapi = yaml.safe_load(output_path.read_text())
        assert openapi["openapi"] == "3.1.0"
        assert openapi["info"]["title"] == "Test App API"

    def test_analyze_produces_endpoints(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        output_path = tmp_path / "spec.yaml"
        runner = CliRunner()

        mock_anthropic = _make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = runner.invoke(
                cli,
                ["analyze", "testapp", "-o", str(output_path)],
            )

        assert result.exit_code == 0
        openapi = yaml.safe_load(output_path.read_text())
        assert len(openapi["paths"]) > 0


class TestAddCommand:
    def test_add_with_app_flag(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        zip_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, zip_path)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["capture", "add", str(zip_path), "--app", "myapp"]
        )

        assert result.exit_code == 0, result.output
        assert "Imported into app 'myapp'" in result.output
        assert "Total captures: 1" in result.output

    def test_add_prompts_for_app(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        zip_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, zip_path)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["capture", "add", str(zip_path)], input="testapp\n"
        )

        assert result.exit_code == 0, result.output
        assert "Imported into app 'testapp'" in result.output

    def test_add_duplicate_prints_warning(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        zip_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, zip_path)

        runner = CliRunner()
        result1 = runner.invoke(
            cli, ["capture", "add", str(zip_path), "--app", "myapp"]
        )
        assert result1.exit_code == 0

        result2 = runner.invoke(
            cli, ["capture", "add", str(zip_path), "--app", "myapp"]
        )
        assert result2.exit_code == 0
        assert "already imported" in result2.output
        assert "Skipping" in result2.output


class TestListCommand:
    def test_list_empty(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "list"])

        assert result.exit_code == 0
        assert "No apps found" in result.output

    def test_list_with_apps(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "alfa")
        store_capture(sample_bundle, "bravo")

        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "list"])

        assert result.exit_code == 0
        assert "alfa" in result.output
        assert "bravo" in result.output


class TestShowCommand:
    def test_show_captures(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "myapp")

        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "show", "myapp"])

        assert result.exit_code == 0
        assert "myapp" in result.output
        assert "1 capture(s)" in result.output

    def test_show_nonexistent_app(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "show", "nope"])

        assert result.exit_code != 0
        assert "not found" in result.output


class TestInspectCommand:
    def test_inspect_summary(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "myapp")

        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "inspect", "myapp"])

        assert result.exit_code == 0
        assert "Test App" in result.output
        assert "test-capture-001" in result.output

    def test_inspect_trace(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "myapp")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["capture", "inspect", "myapp", "--trace", "t_0001"]
        )

        assert result.exit_code == 0
        assert "t_0001" in result.output
        assert "GET" in result.output

    def test_inspect_trace_not_found(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "myapp")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["capture", "inspect", "myapp", "--trace", "t_9999"]
        )

        assert result.exit_code == 0
        assert "not found" in result.output

    def test_inspect_nonexistent_app(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "inspect", "nope"])

        assert result.exit_code != 0
        assert "not found" in result.output


class TestProxyCommand:
    @patch("cli.commands.capture.proxy.run_proxy_to_storage")
    def test_proxy_default_intercepts_all(
        self, mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        mock_run.return_value = (
            CaptureStats(trace_count=5, ws_connection_count=1, ws_message_count=10),
            tmp_path / "store" / "apps" / "myapp" / "captures" / "test",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "proxy", "-a", "myapp"])

        assert result.exit_code == 0
        assert "Intercepting all domains" in result.output
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs.get("allow_hosts") is None

    @patch("cli.commands.capture.proxy.run_proxy_to_storage")
    def test_proxy_with_domains(
        self, mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        mock_run.return_value = (
            CaptureStats(trace_count=3),
            tmp_path / "store" / "apps" / "myapp" / "captures" / "test",
        )
        runner = CliRunner()
        result = runner.invoke(
            cli, ["capture", "proxy", "-a", "myapp", "-d", "api\\.example\\.com"]
        )

        assert result.exit_code == 0
        assert "api\\.example\\.com" in result.output
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs.get("allow_hosts") == ["api\\.example\\.com"]


class TestDiscoverCommand:
    @patch("cli.commands.capture.proxy.run_discover")
    def test_discover_shows_domains(self, mock_discover: MagicMock) -> None:
        mock_discover.return_value = {"api.example.com": 15, "cdn.example.com": 3}
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "discover"])

        assert result.exit_code == 0
        assert "api.example.com" in result.output
        assert "cdn.example.com" in result.output
        assert "Discovered 2 domain(s)" in result.output
        mock_discover.assert_called_once_with(8080)

    @patch("cli.commands.capture.proxy.run_discover")
    def test_discover_empty(self, mock_discover: MagicMock) -> None:
        mock_discover.return_value = {}
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "discover"])

        assert result.exit_code == 0
        assert "No domains discovered" in result.output

    @patch("cli.commands.capture.proxy.run_discover")
    def test_discover_custom_port(self, mock_discover: MagicMock) -> None:
        mock_discover.return_value = {}
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "discover", "-p", "9090"])

        assert result.exit_code == 0
        mock_discover.assert_called_once_with(9090)


def _make_mcp_mock_anthropic() -> MagicMock:
    """Create a mock anthropic module for MCP pipeline tests."""
    identify_call_count = 0

    async def mock_create(**kwargs: Any) -> MagicMock:
        nonlocal identify_call_count
        resp = MagicMock()
        content_block = MagicMock()
        content_block.type = "text"
        resp.stop_reason = "end_turn"

        messages = cast(list[dict[str, Any]], kwargs.get("messages", []))
        prompt = ""
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content", "")
                if isinstance(c, str):
                    prompt = c
                    break

        prompt_lower = prompt.lower()

        if "base url" in prompt_lower and "business api" in prompt_lower:
            content_block.text = json.dumps({"base_url": "https://api.example.com"})
        elif "analyze the authentication" in prompt_lower:
            content_block.text = json.dumps({
                "type": "bearer_token",
                "token_header": "Authorization",
                "token_prefix": "Bearer",
                "obtain_flow": "login_form",
            })
        elif "identify" in prompt_lower and "business capabilit" in prompt_lower:
            identify_call_count += 1
            if identify_call_count == 1:
                content_block.text = json.dumps({
                    "name": "list_users",
                    "description": "List users",
                    "trace_ids": ["t_0001"],
                })
            else:
                content_block.text = json.dumps({"stop": True})
        elif "building an mcp tool" in prompt_lower:
            content_block.text = json.dumps({
                "name": "list_users",
                "description": "List users",
                "parameters": {"type": "object", "properties": {}},
                "request": {"method": "GET", "path": "/api/users"},
            })
        else:
            content_block.text = json.dumps({"stop": True})

        resp.content = [content_block]
        return resp

    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    mock_module = MagicMock()
    mock_module.AsyncAnthropic.return_value = mock_client
    return mock_module


class TestAnalyzeMcpCommand:
    def test_analyze_mcp_basic(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        runner = CliRunner()
        mock_anthropic = _make_mcp_mock_anthropic()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = runner.invoke(
                cli,
                ["analyze", "testapp", "-o", "out", "--mcp"],
            )

        assert result.exit_code == 0, result.output
        assert "tool" in result.output.lower()

        # Verify tools were written
        from cli.helpers.storage import list_tools

        tools = list_tools("testapp")
        assert len(tools) >= 1

    def test_analyze_mcp_updates_app_meta(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import load_app_meta, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        runner = CliRunner()
        mock_anthropic = _make_mcp_mock_anthropic()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = runner.invoke(
                cli,
                ["analyze", "testapp", "-o", "out", "--mcp"],
            )

        assert result.exit_code == 0, result.output
        meta = load_app_meta("testapp")
        assert meta.base_url == "https://api.example.com"


class TestQueryCommand:
    def test_login(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from cli.helpers.storage import ensure_app

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        ensure_app("testapp")

        # Write a mock auth script
        from cli.helpers.storage import auth_script_path

        script_path = auth_script_path("testapp")
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(
            'def acquire_token():\n'
            '    return {"headers": {"Authorization": "Bearer test"}, "expires_in": 3600}\n'
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["query", "login", "testapp"])

        assert result.exit_code == 0, result.output
        assert "Login successful" in result.output

        from cli.helpers.storage import load_token

        token = load_token("testapp")
        assert token is not None
        assert token.headers["Authorization"] == "Bearer test"

    def test_refresh_no_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from cli.helpers.storage import ensure_app

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        ensure_app("testapp")

        runner = CliRunner()
        result = runner.invoke(cli, ["query", "refresh", "testapp"])

        assert result.exit_code != 0
        assert "No token found" in result.output

    def test_refresh_with_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import time

        from cli.formats.mcp_tool import TokenState
        from cli.helpers.storage import auth_script_path, ensure_app, write_token

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        ensure_app("testapp")

        # Write token with refresh_token
        write_token("testapp", TokenState(
            headers={"Authorization": "Bearer old"},
            refresh_token="refresh_tok",
            expires_at=0.0,  # expired
            obtained_at=time.time() - 7200,
        ))

        # Write mock auth script with refresh_token function
        script_path = auth_script_path("testapp")
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(
            'def acquire_token():\n'
            '    return {"headers": {"Authorization": "Bearer new"}}\n'
            'def refresh_token(current_refresh_token):\n'
            '    return {"headers": {"Authorization": "Bearer refreshed"}, "expires_in": 3600}\n'
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["query", "refresh", "testapp"])

        assert result.exit_code == 0, result.output
        assert "Token refreshed" in result.output
