"""Tests for the centralized LLM helper (cli/helpers/llm.py)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import cli.helpers.llm as llm


def _make_text_block(text: str) -> MagicMock:
    """Build a mock content block with type='text'."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_mock_response(text: str = "hello", stop_reason: str = "end_turn") -> MagicMock:
    """Build a mock API response containing a single text block."""
    resp = MagicMock()
    resp.content = [_make_text_block(text)]
    resp.stop_reason = stop_reason
    return resp


def _make_mock_client(response: Any = None) -> MagicMock:
    """Build a mock client whose messages.create returns *response*."""
    client = MagicMock()
    mock_response = response or _make_mock_response()
    client.messages.create = AsyncMock(return_value=mock_response)
    return client


def _make_rate_limit_error(retry_after: str | None = None) -> Exception:
    """Build a fake anthropic.RateLimitError with optional retry-after header."""
    import anthropic

    resp = MagicMock()
    if retry_after is not None:
        resp.headers = {"retry-after": retry_after}
    else:
        resp.headers = {}
    resp.status_code = 429
    resp.json.return_value = {"error": {"message": "rate limited", "type": "rate_limit_error"}}
    return anthropic.RateLimitError(
        message="rate limited",
        response=resp,
        body={"error": {"message": "rate limited", "type": "rate_limit_error"}},
    )


class TestInit:
    def test_init_with_mock_client(self):
        mock = MagicMock()
        llm.init(client=mock, model="m")
        assert llm._client is mock  # pyright: ignore[reportPrivateUsage]
        assert llm._semaphore is not None  # pyright: ignore[reportPrivateUsage]

    def test_init_stores_model(self):
        llm.init(client=MagicMock(), model="claude-test-model")
        assert llm._model == "claude-test-model"  # pyright: ignore[reportPrivateUsage]

    def test_init_custom_concurrency(self):
        llm.init(client=MagicMock(), max_concurrent=3, model="m")
        sem = llm._semaphore  # pyright: ignore[reportPrivateUsage]
        assert sem is not None
        assert sem._value == 3  # pyright: ignore[reportPrivateUsage]

    def test_init_debug_dir(self, tmp_path: Path):
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()
        llm.init(client=MagicMock(), debug_dir=debug_dir, model="m")
        assert llm._debug_dir is debug_dir  # pyright: ignore[reportPrivateUsage]

    def test_reset_clears_all(self, tmp_path: Path):
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()
        llm.init(client=MagicMock(), debug_dir=debug_dir, model="m")
        llm.reset()
        assert llm._debug_dir is None  # pyright: ignore[reportPrivateUsage]
        assert llm._model is None  # pyright: ignore[reportPrivateUsage]


class TestInternalCreate:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """Successful call on first attempt, no retry needed."""
        expected = MagicMock()
        client = _make_mock_client(expected)
        llm.init(client=client, model="m")

        result = await llm._create(model="m", max_tokens=10, messages=[])  # pyright: ignore[reportPrivateUsage]
        assert result is expected
        client.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limit_with_retry_after_header(self):
        """Rate limit -> retry-after header respected -> success on 2nd attempt."""
        expected = MagicMock()
        error = _make_rate_limit_error(retry_after="0.01")

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[error, expected])
        llm.init(client=client, model="m")

        result = await llm._create(model="m", max_tokens=10, messages=[])  # pyright: ignore[reportPrivateUsage]
        assert result is expected
        assert client.messages.create.await_count == 2

    @pytest.mark.asyncio
    async def test_rate_limit_fallback_exponential(self):
        """Rate limit without retry-after -> fallback exponential backoff."""
        expected = MagicMock()
        error = _make_rate_limit_error(retry_after=None)

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[error, expected])
        # Use a tiny backoff so the test runs fast.
        original_backoff = llm.FALLBACK_BACKOFF
        llm.FALLBACK_BACKOFF = 0.01
        try:
            llm.init(client=client, model="m")
            result = await llm._create(model="m", max_tokens=10, messages=[])  # pyright: ignore[reportPrivateUsage]
            assert result is expected
        finally:
            llm.FALLBACK_BACKOFF = original_backoff

    @pytest.mark.asyncio
    async def test_retries_exhausted_reraises(self):
        """All retries exhausted -> original RateLimitError is re-raised."""
        import anthropic

        error = _make_rate_limit_error(retry_after="0.01")

        client = MagicMock()
        client.messages.create = AsyncMock(
            side_effect=[error] * (llm.MAX_RETRIES + 1)
        )
        llm.init(client=client, model="m")

        with pytest.raises(anthropic.RateLimitError):
            await llm._create(model="m", max_tokens=10, messages=[])  # pyright: ignore[reportPrivateUsage]
        assert client.messages.create.await_count == llm.MAX_RETRIES + 1

    @pytest.mark.asyncio
    async def test_non_rate_limit_error_no_retry(self):
        """Non-rate-limit errors propagate immediately without retry."""
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=ValueError("boom"))
        llm.init(client=client, model="m")

        with pytest.raises(ValueError, match="boom"):
            await llm._create(model="m", max_tokens=10, messages=[])  # pyright: ignore[reportPrivateUsage]
        client.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """Semaphore prevents more than max_concurrent calls at once."""
        max_concurrent = 2
        concurrent_count = 0
        peak_concurrent = 0

        async def slow_create(**kwargs: Any) -> MagicMock:
            nonlocal concurrent_count, peak_concurrent
            concurrent_count += 1
            peak_concurrent = max(peak_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            return MagicMock()

        client = MagicMock()
        client.messages.create = slow_create
        llm.init(client=client, max_concurrent=max_concurrent, model="m")

        await asyncio.gather(*[
            llm._create(model="m", max_tokens=10, messages=[])  # pyright: ignore[reportPrivateUsage]
            for _ in range(6)
        ])
        assert peak_concurrent <= max_concurrent

    @pytest.mark.asyncio
    async def test_not_initialized_raises(self):
        """Calling _create() before init() raises RuntimeError."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await llm._create(model="m", max_tokens=10, messages=[])  # pyright: ignore[reportPrivateUsage]


class TestAsk:
    @pytest.mark.asyncio
    async def test_ask_returns_text(self):
        """ask() returns the text content from the LLM response."""
        client = _make_mock_client(_make_mock_response("the answer"))
        llm.init(client=client, model="m")

        result = await llm.ask("what is 1+1?")
        assert result == "the answer"
        client.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ask_uses_stored_model(self):
        """ask() passes the model configured via init() to the API."""
        client = _make_mock_client(_make_mock_response("ok"))
        llm.init(client=client, model="claude-test-123")

        await llm.ask("hello")
        call_kwargs = client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-test-123"

    @pytest.mark.asyncio
    async def test_ask_without_model_raises(self):
        """ask() raises RuntimeError if no model was configured."""
        client = _make_mock_client(_make_mock_response("ok"))
        llm.init(client=client)

        with pytest.raises(RuntimeError, match="No model configured"):
            await llm.ask("hello")

    @pytest.mark.asyncio
    async def test_ask_with_tools_delegates(self):
        """ask() with tools delegates to the tool loop."""
        # First response uses a tool, second gives final text
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "my_tool"
        tool_use_block.input = {"key": "val"}
        tool_use_block.id = "tu_1"

        tool_response = MagicMock()
        tool_response.content = [tool_use_block]
        tool_response.stop_reason = "tool_use"

        final_response = _make_mock_response('{"result": "ok"}')

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[tool_response, final_response])
        llm.init(client=client, model="m")

        tools = [{"name": "my_tool", "description": "test", "input_schema": {"type": "object"}}]
        executors: dict[str, Callable[[dict[str, Any]], str]] = {"my_tool": lambda inp: "tool_output"}

        result = await llm.ask(
            "use the tool",
            tools=tools,
            executors=executors,
        )
        assert result == '{"result": "ok"}'
        assert client.messages.create.await_count == 2

    @pytest.mark.asyncio
    async def test_ask_saves_debug(self, tmp_path: Path):
        """ask() writes a debug file when debug_dir is set."""
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()

        client = _make_mock_client(_make_mock_response("debug test"))
        llm.init(client=client, debug_dir=debug_dir, model="m")

        await llm.ask("hello", label="test_label")

        files = list(debug_dir.iterdir())
        assert len(files) == 1
        content = files[0].read_text()
        assert "=== PROMPT ===" in content
        assert "hello" in content
        assert "=== RESPONSE ===" in content
        assert "debug test" in content
        assert "test_label" in files[0].name

    @pytest.mark.asyncio
    async def test_ask_detects_truncation(self):
        """ask() raises ValueError when the response is truncated (max_tokens)."""
        client = _make_mock_client(_make_mock_response("partial...", stop_reason="max_tokens"))
        llm.init(client=client, model="m")

        with pytest.raises(ValueError, match="LLM response truncated"):
            await llm.ask("hello", max_tokens=100, label="test_trunc")

    @pytest.mark.asyncio
    async def test_tool_loop_detects_truncation(self):
        """_call_with_tools raises ValueError on max_tokens stop_reason."""
        truncated = _make_mock_response("partial", stop_reason="max_tokens")
        client = _make_mock_client(truncated)
        llm.init(client=client, model="m")

        tools = [{"name": "t", "description": "t", "input_schema": {"type": "object"}}]
        executors: dict[str, Callable[[dict[str, Any]], str]] = {"t": lambda inp: "ok"}

        with pytest.raises(ValueError, match="LLM response truncated"):
            await llm.ask("hello", tools=tools, executors=executors)


class TestCompactJson:
    def test_no_spaces_no_newlines(self):
        obj = {"key": "value", "list": [1, 2, 3]}
        result = llm.compact_json(obj)
        assert " " not in result
        assert "\n" not in result
        assert result == '{"key":"value","list":[1,2,3]}'

    def test_unicode_preserved(self):
        obj = {"name": "caf\u00e9", "city": "\u6771\u4eac"}
        result = llm.compact_json(obj)
        assert "caf\u00e9" in result
        assert "\u6771\u4eac" in result
        assert "\\u" not in result


class TestReadableJson:
    def test_collapses_short_blocks(self):
        obj = {"name": "Alice", "tags": ["admin", "user"], "address": {"city": "Paris", "zip": "75001"}}
        result = llm._readable_json(obj)  # pyright: ignore[reportPrivateUsage]
        # Short arrays/objects should be on one line
        assert '[ "admin", "user" ]' in result
        assert '{ "city": "Paris", "zip": "75001" }' in result
        # But the outer object should still be multi-line
        assert "\n" in result

    def test_expands_large_blocks(self):
        obj = {"data": ["a" * 30, "b" * 30, "c" * 30]}
        result = llm._readable_json(obj)  # pyright: ignore[reportPrivateUsage]
        # The inner array is too wide to collapse (>80 chars), so it stays multi-line
        lines = result.strip().splitlines()
        assert len(lines) > 2


class TestReformatDebugText:
    def test_json_paragraphs_reformatted(self):
        blob = '{"key":"value","list":[1,2,3]}'
        text = f"Some preamble text.\n\n{blob}\n\nMore text after."
        result = llm._reformat_debug_text(text)  # pyright: ignore[reportPrivateUsage]
        # The JSON paragraph should be reformatted (readable style)
        assert "Some preamble text." in result
        assert "More text after." in result
        # The reformatted JSON should still contain the data
        assert '"key"' in result
        assert '"value"' in result

    def test_non_json_paragraphs_untouched(self):
        text = "Hello world.\n\nThis is not JSON.\n\nNeither is this."
        result = llm._reformat_debug_text(text)  # pyright: ignore[reportPrivateUsage]
        assert result == text
