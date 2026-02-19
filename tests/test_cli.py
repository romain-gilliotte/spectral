"""Tests for the CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

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
        messages: list[dict[str, str]] = (  # pyright: ignore[reportUnknownVariableType]
            messages_raw if isinstance(messages_raw, list) else []
        )
        first_msg: dict[str, str] = messages[0] if len(messages) > 0 else {}  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
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
    def test_analyze_basic(self, sample_bundle: CaptureBundle, tmp_path: Path) -> None:
        """Test the analyze command with mocked LLM."""
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        output_path = tmp_path / "spec.yaml"
        runner = CliRunner()

        mock_anthropic = _make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = runner.invoke(
                cli,
                [
                    "analyze",
                    str(bundle_path),
                    "-o",
                    str(output_path),
                ],
            )

        assert result.exit_code == 0, result.output
        assert output_path.exists()

        openapi = yaml.safe_load(output_path.read_text())
        assert openapi["openapi"] == "3.1.0"
        assert openapi["info"]["title"] == "Test App API"

    def test_analyze_produces_endpoints(
        self, sample_bundle: CaptureBundle, tmp_path: Path
    ) -> None:
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        output_path = tmp_path / "spec.yaml"
        runner = CliRunner()

        mock_anthropic = _make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = runner.invoke(
                cli,
                [
                    "analyze",
                    str(bundle_path),
                    "-o",
                    str(output_path),
                ],
            )

        assert result.exit_code == 0
        openapi = yaml.safe_load(output_path.read_text())
        assert len(openapi["paths"]) > 0


class TestInspectCommand:
    def test_inspect_summary(
        self, sample_bundle: CaptureBundle, tmp_path: Path
    ) -> None:
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "inspect", str(bundle_path)])

        assert result.exit_code == 0
        assert "Test App" in result.output
        assert "test-capture-001" in result.output

    def test_inspect_trace(self, sample_bundle: CaptureBundle, tmp_path: Path) -> None:
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "inspect", str(bundle_path), "--trace", "t_0001"])

        assert result.exit_code == 0
        assert "t_0001" in result.output
        assert "GET" in result.output

    def test_inspect_trace_not_found(
        self, sample_bundle: CaptureBundle, tmp_path: Path
    ) -> None:
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "inspect", str(bundle_path), "--trace", "t_9999"])

        assert result.exit_code == 0
        assert "not found" in result.output


class TestProxyCommand:
    @patch("cli.commands.capture.proxy.run_proxy")
    def test_proxy_default_intercepts_all(self, mock_run: MagicMock) -> None:
        mock_run.return_value = CaptureStats(trace_count=5, ws_connection_count=1, ws_message_count=10)
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "proxy"])

        assert result.exit_code == 0
        assert "Intercepting all domains" in result.output
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs.get("allow_hosts") is None

    @patch("cli.commands.capture.proxy.run_proxy")
    def test_proxy_with_domains(self, mock_run: MagicMock) -> None:
        mock_run.return_value = CaptureStats(trace_count=3)
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "proxy", "-d", "api\\.example\\.com"])

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
