"""Tests for the CLI commands."""

import json
from pathlib import Path

from click.testing import CliRunner

from cli.capture.loader import write_bundle
from cli.main import cli


class TestAnalyzeCommand:
    def test_analyze_basic(self, sample_bundle, tmp_path):
        """Test the analyze command with --no-llm."""
        bundle_path = tmp_path / "capture.zip"
        write_bundle(sample_bundle, bundle_path)

        output_path = tmp_path / "spec.json"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "analyze", str(bundle_path),
            "-o", str(output_path),
            "--no-llm",
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
        result = runner.invoke(cli, [
            "analyze", str(bundle_path),
            "-o", str(output_path),
            "--no-llm",
        ])

        assert result.exit_code == 0
        spec = json.loads(output_path.read_text())
        endpoints = spec["protocols"]["rest"]["endpoints"]
        assert len(endpoints) > 0


class TestGenerateCommand:
    def _create_spec_file(self, sample_bundle, tmp_path) -> Path:
        """Helper to create a spec file from a sample bundle."""
        from cli.analyze.spec_builder import build_spec

        spec = build_spec(sample_bundle)
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
        result = runner.invoke(cli, [
            "pipeline", str(bundle_path),
            "--types", "openapi,python-client",
            "-o", str(output_dir),
            "--no-llm",
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
