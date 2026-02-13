"""Tests for the CLI commands."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from cli.capture.loader import write_bundle
from cli.main import cli


def _make_mock_anthropic_module():
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

    detail_response = json.dumps({
        "business_purpose": "Test endpoint", "user_story": "As a user, I want to test",
        "correlation_confidence": 0.9, "parameter_meanings": {},
        "response_meanings": {}, "trigger_explanations": [],
    })

    context_response = json.dumps({
        "domain": "Testing", "description": "Test API",
        "user_personas": ["tester"], "key_workflows": [],
        "business_glossary": {},
    })

    async def mock_create(**kwargs):
        mock_response = MagicMock()
        mock_content = MagicMock()
        msg = kwargs.get("messages", [{}])[0].get("content", "")
        if "Group these observed URLs" in msg:
            mock_content.text = groups_response
        elif "authentication" in msg:
            mock_content.text = auth_response
        elif "business domain" in msg or "Based on these API endpoints" in msg:
            mock_content.text = context_response
        else:
            mock_content.text = detail_response
        mock_response.content = [mock_content]
        return mock_response

    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    mock_module = MagicMock()
    mock_module.AsyncAnthropic.return_value = mock_client
    return mock_module


class TestAnalyzeCommand:
    def test_analyze_basic(self, sample_bundle, tmp_path):
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

    def test_analyze_produces_endpoints(self, sample_bundle, tmp_path):
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
    def _create_spec_file(self, sample_bundle, tmp_path) -> Path:
        """Helper to create a spec file from a sample bundle using mocked LLM."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from cli.analyze.spec_builder import build_spec

        mock_client = AsyncMock()

        groups_response = json.dumps([
            {"method": "GET", "pattern": "/api/users", "urls": ["https://api.example.com/api/users"]},
            {"method": "GET", "pattern": "/api/users/{user_id}/orders",
             "urls": ["https://api.example.com/api/users/123/orders", "https://api.example.com/api/users/456/orders"]},
            {"method": "POST", "pattern": "/api/orders", "urls": ["https://api.example.com/api/orders"]},
        ])

        async def mock_create(**kwargs):
            mock_response = MagicMock()
            mock_content = MagicMock()
            msg = kwargs.get("messages", [{}])[0].get("content", "")
            if "Group these observed URLs" in msg:
                mock_content.text = groups_response
            elif "authentication" in msg:
                mock_content.text = json.dumps({"type": "bearer_token", "token_header": "Authorization", "token_prefix": "Bearer"})
            elif "business domain" in msg or "Based on these API endpoints" in msg:
                mock_content.text = json.dumps({"domain": "", "description": "", "user_personas": [], "key_workflows": [], "business_glossary": {}})
            else:
                mock_content.text = json.dumps({"business_purpose": "test", "user_story": "test", "correlation_confidence": 0.5, "parameter_meanings": {}, "response_meanings": {}, "trigger_explanations": []})
            mock_response.content = [mock_content]
            return mock_response

        mock_client.messages.create = mock_create

        spec = asyncio.run(build_spec(sample_bundle, client=mock_client, model="test-model"))
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(spec.model_dump_json(indent=2, by_alias=True))
        return spec_path

    def test_generate_openapi(self, sample_bundle, tmp_path):
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

    def test_generate_python_client(self, sample_bundle, tmp_path):
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

    def test_generate_markdown_docs(self, sample_bundle, tmp_path):
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

    def test_generate_curl_scripts(self, sample_bundle, tmp_path):
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

    def test_generate_mcp_server(self, sample_bundle, tmp_path):
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
    def test_inspect_summary(self, sample_bundle, tmp_path):
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(bundle_path)])

        assert result.exit_code == 0
        assert "Test App" in result.output
        assert "test-capture-001" in result.output

    def test_inspect_trace(self, sample_bundle, tmp_path):
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(bundle_path), "--trace", "t_0001"])

        assert result.exit_code == 0
        assert "t_0001" in result.output
        assert "GET" in result.output

    def test_inspect_trace_not_found(self, sample_bundle, tmp_path):
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(bundle_path), "--trace", "t_9999"])

        assert result.exit_code == 0
        assert "not found" in result.output


class TestPipelineCommand:
    def test_pipeline(self, sample_bundle, tmp_path):
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        output_dir = tmp_path / "output"
        runner = CliRunner()

        mock_anthropic = _make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = runner.invoke(cli, [
                "pipeline", str(bundle_path),
                "--types", "openapi,python-client",
                "-o", str(output_dir),
            ])

        assert result.exit_code == 0, result.output
        assert (output_dir / "api_spec.json").exists()
        assert (output_dir / "openapi.yaml").exists()
        assert (output_dir / "client.py").exists()


class TestHarCommands:
    def test_import_har(self, tmp_path):
        har = {
            "log": {
                "version": "1.2",
                "creator": {"name": "test", "version": "1.0"},
                "entries": [
                    {
                        "startedDateTime": "2026-01-01T00:00:00Z",
                        "time": 100,
                        "request": {
                            "method": "GET",
                            "url": "https://example.com/api/data",
                            "httpVersion": "HTTP/1.1",
                            "headers": [],
                            "queryString": [],
                            "cookies": [],
                            "headersSize": -1,
                            "bodySize": 0,
                        },
                        "response": {
                            "status": 200,
                            "statusText": "OK",
                            "httpVersion": "HTTP/1.1",
                            "headers": [],
                            "cookies": [],
                            "content": {"size": 0, "mimeType": "application/json", "text": "{}"},
                            "redirectURL": "",
                            "headersSize": -1,
                            "bodySize": 0,
                        },
                        "cache": {},
                        "timings": {"dns": 0, "connect": 0, "ssl": 0, "send": 0, "wait": 0, "receive": 0},
                    },
                ],
            }
        }
        har_path = tmp_path / "test.har"
        har_path.write_text(json.dumps(har))

        output_path = tmp_path / "capture.zip"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "import-har", str(har_path),
            "-o", str(output_path),
        ])

        assert result.exit_code == 0, result.output
        assert output_path.exists()

    def test_export_har(self, sample_bundle, tmp_path):
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        har_path = tmp_path / "export.har"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "export-har", str(bundle_path),
            "-o", str(har_path),
        ])

        assert result.exit_code == 0, result.output
        assert har_path.exists()
        har = json.loads(har_path.read_text())
        assert "log" in har
        assert len(har["log"]["entries"]) == len(sample_bundle.traces)
