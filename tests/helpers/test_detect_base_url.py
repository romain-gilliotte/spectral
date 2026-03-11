"""Tests for detect_base_url."""

from typing import Any

from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest

from cli.commands.capture.types import CaptureBundle
from cli.formats.capture_bundle import (
    AppInfo,
    CaptureManifest,
    CaptureStats,
    Timeline,
)
from cli.helpers.detect_base_url import detect_base_url
from cli.helpers.llm._client import set_test_model
from tests.conftest import make_trace


def _make_bundle(traces: list[Any] | None = None) -> CaptureBundle:
    return CaptureBundle(
        manifest=CaptureManifest(
            capture_id="test",
            created_at="2026-01-01T00:00:00Z",
            app=AppInfo(name="T", base_url="http://localhost", title="T"),
            duration_ms=10000,
            stats=CaptureStats(),
        ),
        traces=traces or [],
        contexts=[],
        timeline=Timeline(),
    )


def _setup_llm(text: str) -> None:
    """Set up a FunctionModel that returns the given text (or structured output)."""
    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
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


class TestDetectBaseUrl:
    @pytest.mark.asyncio
    async def test_returns_cached_base_url(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
        """When app.json has base_url cached, return it without LLM call."""
        from cli.formats.app_meta import AppMeta

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "store"))
        app_dir = tmp_path / "store" / "apps" / "myapp"
        app_dir.mkdir(parents=True)
        meta = AppMeta(
            name="myapp", display_name="myapp",
            created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
            base_url="https://cached.example.com/api",
        )
        (app_dir / "app.json").write_text(meta.model_dump_json())

        bundle = _make_bundle([
            make_trace("t_0001", "GET", "https://cached.example.com/api/users", 200, 1000),
        ])
        result = await detect_base_url(bundle, "myapp")
        assert result == "https://cached.example.com/api"

    @pytest.mark.asyncio
    async def test_returns_base_url(self):
        _setup_llm('{"base_url": "https://www.example.com/api"}')

        bundle = _make_bundle([
            make_trace("t_0001", "GET", "https://www.example.com/api/users", 200, 1000),
            make_trace("t_0002", "GET", "https://cdn.example.com/style.css", 200, 2000),
        ])
        result = await detect_base_url(bundle, "testapp")
        assert result == "https://www.example.com/api"

    @pytest.mark.asyncio
    async def test_strips_trailing_slash(self):
        _setup_llm('{"base_url": "https://api.example.com/"}')

        bundle = _make_bundle([
            make_trace("t_0001", "GET", "https://api.example.com/v1", 200, 1000),
        ])
        result = await detect_base_url(bundle, "testapp")
        assert result == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_origin_only(self):
        _setup_llm('{"base_url": "https://api.example.com"}')

        bundle = _make_bundle([
            make_trace("t_0001", "GET", "https://api.example.com/users", 200, 1000),
        ])
        result = await detect_base_url(bundle, "testapp")
        assert result == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_invalid_response_raises(self):
        _setup_llm('{"something_else": "value"}')

        bundle = _make_bundle([
            make_trace("t_0001", "GET", "https://example.com/api", 200, 1000),
        ])
        with pytest.raises((ValidationError, ValueError, Exception)):
            await detect_base_url(bundle, "testapp")
