"""Tests for the auth extract command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from click.testing import CliRunner
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest

from cli.commands.capture.types import CaptureBundle
from cli.formats.capture_bundle import Header
from cli.helpers.llm._client import set_test_model
from cli.main import cli
from tests.conftest import make_trace


def _setup_extract_llm(*responses: str) -> None:
    """Set up a FunctionModel that returns given responses in order."""
    call_count = {"n": 0}
    response_list = list(responses)

    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        idx = min(call_count["n"], len(response_list) - 1)
        call_count["n"] += 1
        text = response_list[idx]
        if info.output_tools:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args=text,
                    tool_call_id=f"tc_{idx}",
                ),
            ])
        return ModelResponse(parts=[TextPart(content=text)])

    set_test_model(FunctionModel(model_fn))


class TestExtractAuthorizationHeader:
    """Fast path: Authorization header found directly."""

    def test_extract_authorization_header(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Traces with Authorization header -> token.json written (no LLM needed for auth)."""
        from cli.helpers.storage import load_token, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        store_capture(sample_bundle, "testapp")

        # LLM only needed for base_url detection (sample_bundle has no cached base_url)
        _setup_extract_llm('{"base_url": "https://api.example.com"}')

        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "extract", "testapp"])

        assert result.exit_code == 0, result.output
        assert "Token saved" in result.output
        assert "Authorization" in result.output

        token = load_token("testapp")
        assert token is not None
        assert "Authorization" in token.headers
        assert token.headers["Authorization"] == "Bearer token123"

    def test_extract_most_recent_trace(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Multiple traces with different tokens -> picks most recent."""
        from cli.helpers.storage import load_token, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))

        # Add a newer trace with a different token
        newer_trace = make_trace(
            "t_0005",
            "GET",
            "https://api.example.com/api/profile",
            200,
            timestamp=2000000,
            request_headers=[Header(name="Authorization", value="Bearer newer-token")],
        )
        sample_bundle.traces.append(newer_trace)
        store_capture(sample_bundle, "testapp")

        _setup_extract_llm('{"base_url": "https://api.example.com"}')

        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "extract", "testapp"])

        assert result.exit_code == 0, result.output
        token = load_token("testapp")
        assert token is not None
        assert token.headers["Authorization"] == "Bearer newer-token"


class TestExtractCookieViaLlm:
    """LLM fallback: no Authorization header, LLM identifies Cookie."""

    def test_extract_cookie_via_llm(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import load_token, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))

        # Replace all traces with cookie-only traces (no Authorization header)
        sample_bundle.traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/api/data",
                200,
                timestamp=1000000,
                request_headers=[
                    Header(name="Cookie", value="session=abc123; csrf=xyz"),
                    Header(name="Content-Type", value="application/json"),
                ],
            ),
        ]
        store_capture(sample_bundle, "testapp")

        _setup_extract_llm(
            '{"base_url": "https://api.example.com"}',
            '{"header_names": ["Cookie"]}',
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "extract", "testapp"])

        assert result.exit_code == 0, result.output
        assert "Token saved" in result.output

        token = load_token("testapp")
        assert token is not None
        assert "Cookie" in token.headers
        assert token.headers["Cookie"] == "session=abc123; csrf=xyz"


class TestExtractNoAuth:
    """No auth headers found at all."""

    def test_extract_no_auth_headers(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import load_token, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))

        # Traces with no auth-related headers
        sample_bundle.traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/api/public",
                200,
                timestamp=1000000,
                request_headers=[
                    Header(name="Content-Type", value="application/json"),
                    Header(name="Accept", value="*/*"),
                ],
            ),
        ]
        store_capture(sample_bundle, "testapp")

        # base_url detection, then LLM says no auth headers
        _setup_extract_llm(
            '{"base_url": "https://api.example.com"}',
            '{"header_names": []}',
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "extract", "testapp"])

        assert result.exit_code == 0, result.output
        assert "No auth headers found" in result.output

        token = load_token("testapp")
        assert token is None


class TestExtractNoMatchingTraces:
    """No traces match base_url."""

    def test_extract_no_matching_traces(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import load_token, store_capture

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))

        # All traces go to a different domain
        sample_bundle.traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://other-api.example.com/data",
                200,
                timestamp=1000000,
                request_headers=[Header(name="Authorization", value="Bearer tok")],
            ),
        ]
        store_capture(sample_bundle, "testapp")

        # base_url is different from the traces' URLs
        _setup_extract_llm('{"base_url": "https://api.example.com"}')

        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "extract", "testapp"])

        assert result.exit_code == 0, result.output
        assert "No auth headers found" in result.output

        token = load_token("testapp")
        assert token is None


class TestExtractNonexistentApp:
    def test_extract_nonexistent_app(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "extract", "nope"])

        assert result.exit_code != 0
        assert "not found" in result.output
