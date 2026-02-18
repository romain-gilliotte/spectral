"""Tests for the CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from cli.capture.loader import write_bundle
from cli.capture.models import CaptureBundle
from cli.main import cli


def _make_mock_anthropic_module() -> MagicMock:
    """Create a mock anthropic module with AsyncAnthropic client."""

    # Standard LLM responses for the pipeline
    groups_response = json.dumps([
        {"method": "GET", "pattern": "/api/users", "urls": ["https://api.example.com/api/users"]},
        {"method": "GET", "pattern": "/api/users/{user_id}/orders",
         "urls": ["https://api.example.com/api/users/123/orders", "https://api.example.com/api/users/456/orders"]},
        {"method": "POST", "pattern": "/api/orders", "urls": ["https://api.example.com/api/orders"]},
    ])

    auth_response = json.dumps({
        "type": "bearer_token", "token_header": "Authorization",
        "token_prefix": "Bearer", "business_process": "Token auth",
        "user_journey": ["Login"], "obtain_flow": "login_form",
    })

    enrich_response = json.dumps({
        "endpoints": {},
        "business_context": {
            "domain": "Testing", "description": "Test API",
            "user_personas": ["tester"], "key_workflows": [],
            "business_glossary": {},
        },
    })

    base_url_response = json.dumps({"base_url": "https://api.example.com"})

    async def mock_create(**kwargs: object) -> MagicMock:
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_response.stop_reason = "end_turn"
        messages_raw = kwargs.get("messages")
        messages: list[dict[str, str]] = messages_raw if isinstance(messages_raw, list) else []  # pyright: ignore[reportUnknownVariableType]
        first_msg: dict[str, str] = messages[0] if len(messages) > 0 else {}  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
        msg: str = str(first_msg.get("content", ""))
        if "base URL" in msg and "business API" in msg:
            mock_content.text = base_url_response
        elif "Group these observed URLs" in msg:
            mock_content.text = groups_response
        elif "authentication" in msg:
            mock_content.text = auth_response
        elif "SINGLE JSON response" in msg:
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

        output_path = tmp_path / "spec.json"
        runner = CliRunner()

        mock_anthropic = _make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = runner.invoke(cli, [
                "analyze", str(bundle_path),
                "-o", str(output_path),
            ])

        assert result.exit_code == 0, result.output
        assert output_path.exists()

        spec = json.loads(output_path.read_text())
        assert "api_spec_version" in spec
        assert spec["name"] == "Test App API"

    def test_analyze_produces_endpoints(self, sample_bundle: CaptureBundle, tmp_path: Path) -> None:
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        output_path = tmp_path / "spec.json"
        runner = CliRunner()

        mock_anthropic = _make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = runner.invoke(cli, [
                "analyze", str(bundle_path),
                "-o", str(output_path),
            ])

        assert result.exit_code == 0
        spec = json.loads(output_path.read_text())
        endpoints = spec["protocols"]["rest"]["endpoints"]
        assert len(endpoints) > 0


class TestGenerateCommand:
    def _create_spec_file(self, sample_bundle: CaptureBundle, tmp_path: Path) -> Path:
        """Helper to create a spec file from a sample bundle using mocked LLM."""
        import asyncio
        from cli.analyze.pipeline import build_spec

        mock_client = AsyncMock()

        groups_response = json.dumps([
            {"method": "GET", "pattern": "/api/users", "urls": ["https://api.example.com/api/users"]},
            {"method": "GET", "pattern": "/api/users/{user_id}/orders",
             "urls": ["https://api.example.com/api/users/123/orders", "https://api.example.com/api/users/456/orders"]},
            {"method": "POST", "pattern": "/api/orders", "urls": ["https://api.example.com/api/orders"]},
        ])

        enrich_response = json.dumps({
            "endpoints": {},
            "business_context": {
                "domain": "", "description": "", "user_personas": [],
                "key_workflows": [], "business_glossary": {},
            },
        })

        async def mock_create(**kwargs: object) -> MagicMock:
            mock_response = MagicMock()
            mock_content = MagicMock()
            mock_content.type = "text"
            mock_response.stop_reason = "end_turn"
            messages_raw = kwargs.get("messages")
            messages: list[dict[str, str]] = messages_raw if isinstance(messages_raw, list) else []  # pyright: ignore[reportUnknownVariableType]
            first_msg: dict[str, str] = messages[0] if len(messages) > 0 else {}  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
            msg: str = str(first_msg.get("content", ""))
            if "base URL" in msg and "business API" in msg:
                mock_content.text = json.dumps({"base_url": "https://api.example.com"})
            elif "Group these observed URLs" in msg:
                mock_content.text = groups_response
            elif "authentication" in msg:
                mock_content.text = json.dumps({"type": "bearer_token", "token_header": "Authorization", "token_prefix": "Bearer"})
            elif "SINGLE JSON response" in msg:
                mock_content.text = enrich_response
            else:
                mock_content.text = enrich_response
            mock_response.content = [mock_content]
            return mock_response

        mock_client.messages.create = mock_create

        spec = asyncio.run(build_spec(sample_bundle, client=mock_client, model="test-model"))
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(spec.model_dump_json(indent=2, by_alias=True))
        return spec_path

    def test_generate_openapi(self, sample_bundle: CaptureBundle, tmp_path: Path) -> None:
        spec_path = self._create_spec_file(sample_bundle, tmp_path)
        output_path = tmp_path / "openapi.yaml"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate", str(spec_path),
            "--type", "openapi",
            "-o", str(output_path),
        ])

        assert result.exit_code == 0, result.output
        assert output_path.exists()

    def test_generate_python_client(self, sample_bundle: CaptureBundle, tmp_path: Path) -> None:
        spec_path = self._create_spec_file(sample_bundle, tmp_path)
        output_path = tmp_path / "client.py"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate", str(spec_path),
            "--type", "python-client",
            "-o", str(output_path),
        ])

        assert result.exit_code == 0, result.output
        assert output_path.exists()

    def test_generate_markdown_docs(self, sample_bundle: CaptureBundle, tmp_path: Path) -> None:
        spec_path = self._create_spec_file(sample_bundle, tmp_path)
        output_path = tmp_path / "docs"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate", str(spec_path),
            "--type", "markdown-docs",
            "-o", str(output_path),
        ])

        assert result.exit_code == 0, result.output
        assert (output_path / "index.md").exists()

    def test_generate_curl_scripts(self, sample_bundle: CaptureBundle, tmp_path: Path) -> None:
        spec_path = self._create_spec_file(sample_bundle, tmp_path)
        output_path = tmp_path / "scripts"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate", str(spec_path),
            "--type", "curl-scripts",
            "-o", str(output_path),
        ])

        assert result.exit_code == 0, result.output
        assert (output_path / "all_requests.sh").exists()

    def test_generate_mcp_server(self, sample_bundle: CaptureBundle, tmp_path: Path) -> None:
        spec_path = self._create_spec_file(sample_bundle, tmp_path)
        output_path = tmp_path / "mcp-server"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate", str(spec_path),
            "--type", "mcp-server",
            "-o", str(output_path),
        ])

        assert result.exit_code == 0, result.output
        assert (output_path / "server.py").exists()


class TestInspectCommand:
    def test_inspect_summary(self, sample_bundle: CaptureBundle, tmp_path: Path) -> None:
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(bundle_path)])

        assert result.exit_code == 0
        assert "Test App" in result.output
        assert "test-capture-001" in result.output

    def test_inspect_trace(self, sample_bundle: CaptureBundle, tmp_path: Path) -> None:
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(bundle_path), "--trace", "t_0001"])

        assert result.exit_code == 0
        assert "t_0001" in result.output
        assert "GET" in result.output

    def test_inspect_trace_not_found(self, sample_bundle: CaptureBundle, tmp_path: Path) -> None:
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(bundle_path), "--trace", "t_9999"])

        assert result.exit_code == 0
        assert "not found" in result.output


class TestCallCommand:
    def _create_spec_file(self, tmp_path: Path) -> Path:
        """Create a minimal spec file for call command testing."""
        from cli.formats.api_spec import (
            ApiSpec,
            AuthInfo,
            EndpointSpec,
            ParameterSpec,
            Protocols,
            RequestSpec,
            ResponseSpec,
            RestProtocol,
        )

        spec = ApiSpec(
            name="Test API",
            auth=AuthInfo(type="bearer_token", token_header="Authorization", token_prefix="Bearer"),
            protocols=Protocols(
                rest=RestProtocol(
                    base_url="https://api.example.com",
                    endpoints=[
                        EndpointSpec(
                            id="get_users",
                            path="/api/users",
                            method="GET",
                            business_purpose="List users",
                            request=RequestSpec(parameters=[
                                ParameterSpec(name="limit", location="query", type="integer"),
                            ]),
                            responses=[ResponseSpec(status=200)],
                        ),
                        EndpointSpec(
                            id="get_user",
                            path="/api/users/{user_id}",
                            method="GET",
                            business_purpose="Get a user",
                            request=RequestSpec(parameters=[
                                ParameterSpec(name="user_id", location="path", type="string", required=True),
                            ]),
                            responses=[ResponseSpec(status=200)],
                        ),
                    ],
                ),
            ),
        )
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(spec.model_dump_json(indent=2, by_alias=True))
        return spec_path

    def test_call_list(self, tmp_path: Path) -> None:
        spec_path = self._create_spec_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["call", str(spec_path), "--list", "--token", "tok"])
        assert result.exit_code == 0
        assert "get_users" in result.output
        assert "get_user" in result.output

    def test_call_list_no_args(self, tmp_path: Path) -> None:
        """When no endpoint is specified, should list endpoints."""
        spec_path = self._create_spec_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["call", str(spec_path), "--token", "tok"])
        assert result.exit_code == 0
        assert "get_users" in result.output

    @patch("cli.client.client.requests.Session")
    def test_call_endpoint(self, mock_session_cls: MagicMock, tmp_path: Path) -> None:
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'[{"id": 1}]'
        mock_resp.json.return_value = [{"id": 1}]
        mock_resp.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        spec_path = self._create_spec_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "call", str(spec_path), "get_users", "limit=10", "--token", "tok",
        ])
        assert result.exit_code == 0

    def test_call_invalid_param_format(self, tmp_path: Path) -> None:
        spec_path = self._create_spec_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "call", str(spec_path), "get_users", "badparam", "--token", "tok",
        ])
        assert result.exit_code != 0


