"""Tests for detect_base_url."""

from typing import Any
from unittest.mock import MagicMock

from pydantic import ValidationError
import pytest

from cli.commands.capture.types import CaptureBundle
from cli.formats.capture_bundle import (
    AppInfo,
    CaptureManifest,
    CaptureStats,
    Timeline,
)
from cli.helpers.detect_base_url import detect_base_url
from cli.helpers.llm._client import setup_client
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


def _make_text_response(text: str) -> MagicMock:
    """Create a mock response with a single text block and end_turn stop."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    return resp


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
        """detect_base_url should parse the LLM response and return the base_url string."""

        async def mock_create(**kwargs: Any) -> MagicMock:
            return _make_text_response('{"base_url": "https://www.example.com/api"}')

        client = MagicMock()
        client.messages.create = mock_create
        setup_client(client)

        bundle = _make_bundle([
            make_trace("t_0001", "GET", "https://www.example.com/api/users", 200, 1000),
            make_trace("t_0002", "GET", "https://cdn.example.com/style.css", 200, 2000),
        ])
        result = await detect_base_url(bundle, "testapp")
        assert result == "https://www.example.com/api"

    @pytest.mark.asyncio
    async def test_strips_trailing_slash(self):
        """Trailing slash should be stripped from the returned base URL."""

        async def mock_create(**kwargs: Any) -> MagicMock:
            return _make_text_response('{"base_url": "https://api.example.com/"}')

        client = MagicMock()
        client.messages.create = mock_create
        setup_client(client)

        bundle = _make_bundle([
            make_trace("t_0001", "GET", "https://api.example.com/v1", 200, 1000),
        ])
        result = await detect_base_url(bundle, "testapp")
        assert result == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_origin_only(self):
        """LLM may return just the origin without a path prefix."""

        async def mock_create(**kwargs: Any) -> MagicMock:
            return _make_text_response('{"base_url": "https://api.example.com"}')

        client = MagicMock()
        client.messages.create = mock_create
        setup_client(client)

        bundle = _make_bundle([
            make_trace("t_0001", "GET", "https://api.example.com/users", 200, 1000),
        ])
        result = await detect_base_url(bundle, "testapp")
        assert result == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_invalid_response_raises(self):
        """If the LLM doesn't return {base_url: ...}, raise ValueError."""

        async def mock_create(**kwargs: Any) -> MagicMock:
            return _make_text_response('{"something_else": "value"}')

        client = MagicMock()
        client.messages.create = mock_create
        setup_client(client)

        bundle = _make_bundle([
            make_trace("t_0001", "GET", "https://example.com/api", 200, 1000),
        ])
        with pytest.raises((ValidationError, ValueError)):
            await detect_base_url(bundle, "testapp")
