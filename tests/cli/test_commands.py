"""Tests for the CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest
import yaml

from cli.commands.capture.types import CaptureBundle
from cli.formats.capture_bundle import CaptureStats
from cli.helpers.llm._client import set_test_model
from cli.main import cli


def _extract_user_prompt(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    return str(part.content)
    return ""


def _extract_system_text(messages: list[Any]) -> str:
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, SystemPromptPart):
                    parts.append(part.content)
    return " ".join(parts)


def _setup_openapi_llm() -> None:
    """Set up a FunctionModel for OpenAPI analysis tests."""

    groups_response = json.dumps(
        {"items": [
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
        ]}
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

    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        prompt = _extract_user_prompt(messages)

        if "base URL" in prompt and "business API" in prompt:
            text = base_url_response
        elif "Group these observed URLs" in prompt:
            text = groups_response
        elif "single API endpoint" in prompt:
            text = enrich_response
        else:
            text = enrich_response

        if info.output_tools:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args=text,
                    tool_call_id="tc_result",
                ),
            ])
        return ModelResponse(parts=[TextPart(content=text)])

    set_test_model(FunctionModel(model_fn))


class TestAnalyzeCommand:
    def test_analyze_basic(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test the openapi analyze command with mocked LLM."""
        from cli.helpers.storage import store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        output_path = tmp_path / "spec.yaml"
        runner = CliRunner()

        _setup_openapi_llm()
        result = runner.invoke(
            cli,
            ["openapi", "analyze", "testapp", "-o", str(output_path)],
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

        _setup_openapi_llm()
        result = runner.invoke(
            cli,
            ["openapi", "analyze", "testapp", "-o", str(output_path)],
        )

        assert result.exit_code == 0
        openapi = yaml.safe_load(output_path.read_text())
        assert len(openapi["paths"]) > 0


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
    @patch("cli.commands.capture.proxy._run_proxy_to_storage")
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

    @patch("cli.commands.capture.proxy._run_proxy_to_storage")
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
    @patch("cli.commands.capture.discover._run_discover")
    def test_discover_shows_domains(self, mock_discover: MagicMock) -> None:
        mock_discover.return_value = {"api.example.com": 15, "cdn.example.com": 3}
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "discover"])

        assert result.exit_code == 0
        assert "api.example.com" in result.output
        assert "cdn.example.com" in result.output
        assert "Discovered 2 domain(s)" in result.output
        mock_discover.assert_called_once_with(8080)

    @patch("cli.commands.capture.discover._run_discover")
    def test_discover_empty(self, mock_discover: MagicMock) -> None:
        mock_discover.return_value = {}
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "discover"])

        assert result.exit_code == 0
        assert "No domains discovered" in result.output

    @patch("cli.commands.capture.discover._run_discover")
    def test_discover_custom_port(self, mock_discover: MagicMock) -> None:
        mock_discover.return_value = {}
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "discover", "-p", "9090"])

        assert result.exit_code == 0
        mock_discover.assert_called_once_with(9090)


def _setup_mcp_llm() -> None:
    """Set up a FunctionModel for MCP pipeline tests."""
    identify_call_count = {"n": 0}

    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        prompt = _extract_user_prompt(messages)
        system_text = _extract_system_text(messages)
        prompt_lower = prompt.lower()
        full_text_lower = (prompt + " " + system_text).lower()

        if "base url" in prompt_lower and "business api" in prompt_lower:
            text = json.dumps({"base_url": "https://api.example.com"})
        elif "target trace:" in prompt_lower and "business capability" in full_text_lower:
            identify_call_count["n"] += 1
            if identify_call_count["n"] == 1:
                text = json.dumps({
                    "useful": True,
                    "name": "list_users",
                    "description": "List users",
                })
            else:
                text = json.dumps({"useful": False})
        elif "candidate:" in prompt_lower and "tool definition" in full_text_lower:
            text = json.dumps({
                "tool": {
                    "name": "list_users",
                    "description": "List users",
                    "parameters": {"type": "object", "properties": {}},
                    "request": {"method": "GET", "path": "/api/users"},
                },
                "consumed_trace_ids": ["t_0001"],
            })
        else:
            text = json.dumps({"useful": False})

        if info.output_tools:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args=text,
                    tool_call_id="tc_result",
                ),
            ])
        return ModelResponse(parts=[TextPart(content=text)])

    set_test_model(FunctionModel(model_fn))


class TestAnalyzeMcpCommand:
    def test_analyze_mcp_basic(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        runner = CliRunner()
        _setup_mcp_llm()
        result = runner.invoke(
            cli,
            ["mcp", "analyze", "testapp"],
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
        _setup_mcp_llm()
        result = runner.invoke(
            cli,
            ["mcp", "analyze", "testapp"],
        )

        assert result.exit_code == 0, result.output
        meta = load_app_meta("testapp")
        assert meta.base_url == "https://api.example.com"


class TestAuthLoginCommand:
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
        result = runner.invoke(cli, ["auth", "login", "testapp"])

        assert result.exit_code == 0, result.output
        assert "Login successful" in result.output

        from cli.helpers.storage import load_token

        token = load_token("testapp")
        assert token is not None
        assert token.headers["Authorization"] == "Bearer test"


class TestAuthLogoutCommand:
    def test_logout_with_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import time

        from cli.formats.mcp_tool import TokenState
        from cli.helpers.storage import ensure_app, load_token, write_token

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        ensure_app("testapp")
        write_token("testapp", TokenState(
            headers={"Authorization": "Bearer test"},
            obtained_at=time.time(),
        ))

        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "logout", "testapp"])

        assert result.exit_code == 0, result.output
        assert "Logged out" in result.output
        assert load_token("testapp") is None

    def test_logout_no_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from cli.helpers.storage import ensure_app

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        ensure_app("testapp")

        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "logout", "testapp"])

        assert result.exit_code == 0, result.output
        assert "No token found" in result.output

    def test_logout_nonexistent_app(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))

        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "logout", "nope"])

        assert result.exit_code != 0
        assert "not found" in result.output


class TestAuthRefreshCommand:
    def test_refresh_no_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from cli.helpers.storage import ensure_app

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        ensure_app("testapp")

        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "refresh", "testapp"])

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
        result = runner.invoke(cli, ["auth", "refresh", "testapp"])

        assert result.exit_code == 0, result.output
        assert "Token refreshed" in result.output
