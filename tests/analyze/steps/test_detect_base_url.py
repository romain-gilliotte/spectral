"""Tests for DetectBaseUrlStep."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from cli.commands.analyze.steps.detect_base_url import DetectBaseUrlStep
from cli.commands.analyze.steps.types import MethodUrlPair
import cli.helpers.llm as llm


def _make_text_response(text: str) -> MagicMock:
    """Create a mock response with a single text block and end_turn stop."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    return resp


class TestDetectBaseUrlStep:
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

        step = DetectBaseUrlStep(app_name="myapp")
        result = await step.run(
            [MethodUrlPair("GET", "https://cached.example.com/api/users")],
        )
        assert result == "https://cached.example.com/api"

    @pytest.mark.asyncio
    async def test_returns_base_url(self):
        """DetectBaseUrlStep should parse the LLM response and return the base_url string."""

        async def mock_create(**kwargs: Any) -> MagicMock:
            return _make_text_response('{"base_url": "https://www.example.com/api"}')

        client = MagicMock()
        client.messages.create = mock_create
        llm.init(client=client, model="test")

        step = DetectBaseUrlStep()
        result = await step.run(
            [
                MethodUrlPair("GET", "https://www.example.com/api/users"),
                MethodUrlPair("GET", "https://cdn.example.com/style.css"),
            ],
        )
        assert result == "https://www.example.com/api"

    @pytest.mark.asyncio
    async def test_strips_trailing_slash(self):
        """Trailing slash should be stripped from the returned base URL."""

        async def mock_create(**kwargs: Any) -> MagicMock:
            return _make_text_response('{"base_url": "https://api.example.com/"}')

        client = MagicMock()
        client.messages.create = mock_create
        llm.init(client=client, model="test")

        step = DetectBaseUrlStep()
        result = await step.run([MethodUrlPair("GET", "https://api.example.com/v1")])
        assert result == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_origin_only(self):
        """LLM may return just the origin without a path prefix."""

        async def mock_create(**kwargs: Any) -> MagicMock:
            return _make_text_response('{"base_url": "https://api.example.com"}')

        client = MagicMock()
        client.messages.create = mock_create
        llm.init(client=client, model="test")

        step = DetectBaseUrlStep()
        result = await step.run([MethodUrlPair("GET", "https://api.example.com/users")])
        assert result == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_invalid_response_raises(self):
        """If the LLM doesn't return {base_url: ...}, raise ValueError."""

        async def mock_create(**kwargs: Any) -> MagicMock:
            return _make_text_response('{"something_else": "value"}')

        client = MagicMock()
        client.messages.create = mock_create
        llm.init(client=client, model="test")

        step = DetectBaseUrlStep()
        with pytest.raises(ValueError, match="Expected"):
            await step.run([MethodUrlPair("GET", "https://example.com/api")])
