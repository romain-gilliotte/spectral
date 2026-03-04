"""Tests for the centralized LLM helper (cli/helpers/llm.py)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from pydantic import BaseModel
import pytest

import cli.helpers.llm as llm


class _SampleModel(BaseModel):
    useful: bool
    name: str | None = None


def _make_text_block(text: str) -> MagicMock:
    """Build a mock content block with type='text'."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_mock_response(
    text: str = "hello",
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> MagicMock:
    """Build a mock API response containing a single text block."""
    resp = MagicMock()
    resp.content = [_make_text_block(text)]
    resp.stop_reason = stop_reason
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
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
        assert llm._client is mock
        assert llm._semaphore is not None

    def test_init_stores_model(self):
        llm.init(client=MagicMock(), model="claude-test-model")
        assert llm._model == "claude-test-model"

    def test_init_custom_concurrency(self):
        llm.init(client=MagicMock(), max_concurrent=3, model="m")
        sem = llm._semaphore
        assert sem is not None
        assert sem._value == 3

    def test_init_debug_dir(self, tmp_path: Path):
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()
        llm.init(client=MagicMock(), debug_dir=debug_dir, model="m")
        assert llm._debug_dir is debug_dir

    def test_reset_clears_all(self, tmp_path: Path):
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()
        llm.init(client=MagicMock(), debug_dir=debug_dir, model="m")
        llm.reset()
        assert llm._debug_dir is None
        assert llm._model is None


class TestInternalCreate:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """Successful call on first attempt, no retry needed."""
        expected = MagicMock()
        client = _make_mock_client(expected)
        llm.init(client=client, model="m")

        result = await llm._create(model="m", max_tokens=10, messages=[])
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

        result = await llm._create(model="m", max_tokens=10, messages=[])
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
            result = await llm._create(model="m", max_tokens=10, messages=[])
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
            await llm._create(model="m", max_tokens=10, messages=[])
        assert client.messages.create.await_count == llm.MAX_RETRIES + 1

    @pytest.mark.asyncio
    async def test_non_rate_limit_error_no_retry(self):
        """Non-rate-limit errors propagate immediately without retry."""
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=ValueError("boom"))
        llm.init(client=client, model="m")

        with pytest.raises(ValueError, match="boom"):
            await llm._create(model="m", max_tokens=10, messages=[])
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
            llm._create(model="m", max_tokens=10, messages=[])
            for _ in range(6)
        ])
        assert peak_concurrent <= max_concurrent

    @pytest.mark.asyncio
    async def test_not_initialized_raises(self):
        """Calling _create() before init() raises RuntimeError."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await llm._create(model="m", max_tokens=10, messages=[])


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


class TestSystemParam:
    @pytest.mark.asyncio
    async def test_ask_passes_system_string(self):
        """ask(system='...') passes system blocks to _create."""
        client = _make_mock_client(_make_mock_response("ok"))
        llm.init(client=client, model="m")

        await llm.ask("hello", system="You are a helpful assistant.")

        call_kwargs = client.messages.create.call_args.kwargs
        assert "system" in call_kwargs
        blocks = call_kwargs["system"]
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"
        assert blocks[0]["text"] == "You are a helpful assistant."
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}

    @pytest.mark.asyncio
    async def test_ask_passes_system_list(self):
        """ask(system=[...]) passes multiple system blocks."""
        client = _make_mock_client(_make_mock_response("ok"))
        llm.init(client=client, model="m")

        await llm.ask("hello", system=["block1", "block2"])

        call_kwargs = client.messages.create.call_args.kwargs
        blocks = call_kwargs["system"]
        assert len(blocks) == 2
        assert blocks[0]["text"] == "block1"
        assert blocks[1]["text"] == "block2"
        assert all(b["cache_control"] == {"type": "ephemeral"} for b in blocks)

    @pytest.mark.asyncio
    async def test_ask_no_system_omits_kwarg(self):
        """ask() without system does not pass system kwarg."""
        client = _make_mock_client(_make_mock_response("ok"))
        llm.init(client=client, model="m")

        await llm.ask("hello")

        call_kwargs = client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    @pytest.mark.asyncio
    async def test_ask_system_with_tools(self):
        """ask(system=..., tools=...) passes system through tool loop."""
        final_response = _make_mock_response("done")
        client = _make_mock_client(final_response)
        llm.init(client=client, model="m")

        tools = [{"name": "t", "description": "t", "input_schema": {"type": "object"}}]
        executors: dict[str, Callable[[dict[str, Any]], str]] = {"t": lambda inp: "ok"}

        await llm.ask("hello", system="sys", tools=tools, executors=executors)

        call_kwargs = client.messages.create.call_args.kwargs
        blocks = call_kwargs["system"]
        assert len(blocks) == 1
        assert blocks[0]["text"] == "sys"


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
        result = llm._readable_json(obj)
        # Short arrays/objects should be on one line
        assert '["admin", "user"]' in result
        assert '{"city": "Paris", "zip": "75001"}' in result
        # But the outer object should still be multi-line
        assert "\n" in result

    def test_expands_large_blocks(self):
        obj = {"data": ["a" * 30, "b" * 30, "c" * 30]}
        result = llm._readable_json(obj)
        # The inner array is too wide to collapse (>80 chars), so it stays multi-line
        lines = result.strip().splitlines()
        assert len(lines) > 2


class TestReformatDebugText:
    def test_json_paragraphs_reformatted(self):
        blob = '{"key":"value","list":[1,2,3]}'
        text = f"Some preamble text.\n\n{blob}\n\nMore text after."
        result = llm._reformat_debug_text(text)
        # The JSON paragraph should be reformatted (readable style)
        assert "Some preamble text." in result
        assert "More text after." in result
        # The reformatted JSON should still contain the data
        assert '"key"' in result
        assert '"value"' in result

    def test_non_json_paragraphs_untouched(self):
        text = "Hello world.\n\nThis is not JSON.\n\nNeither is this."
        result = llm._reformat_debug_text(text)
        assert result == text


class TestUsageTracking:
    def test_get_usage_zero_after_init(self):
        """get_usage() returns (0, 0) right after init()."""
        llm.init(client=MagicMock(), model="m")
        assert llm.get_usage() == (0, 0)

    @pytest.mark.asyncio
    async def test_tokens_accumulate_after_ask(self):
        """Token counts accumulate across multiple ask() calls."""
        resp1 = _make_mock_response("a", input_tokens=100, output_tokens=50)
        resp2 = _make_mock_response("b", input_tokens=200, output_tokens=80)
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[resp1, resp2])
        llm.init(client=client, model="m")

        await llm.ask("first")
        assert llm.get_usage() == (100, 50)

        await llm.ask("second")
        assert llm.get_usage() == (300, 130)

    def test_reset_clears_usage(self):
        """reset() resets token counters to zero."""
        llm.init(client=MagicMock(), model="m")
        # Manually bump counters to simulate usage
        llm._total_input_tokens = 500
        llm._total_output_tokens = 200
        llm.reset()
        assert llm.get_usage() == (0, 0)

    def test_get_cache_usage_zero_after_init(self):
        """get_cache_usage() returns (0, 0) right after init()."""
        llm.init(client=MagicMock(), model="m")
        assert llm.get_cache_usage() == (0, 0)

    def test_reset_clears_cache_usage(self):
        """reset() resets cache token counters to zero."""
        llm.init(client=MagicMock(), model="m")
        llm._total_cache_read_tokens = 1000
        llm._total_cache_creation_tokens = 500
        llm.reset()
        assert llm.get_cache_usage() == (0, 0)

    @pytest.mark.asyncio
    async def test_cache_tokens_accumulate(self):
        """Cache token counts accumulate from response usage."""
        resp = _make_mock_response("a", input_tokens=100, output_tokens=50)
        resp.usage.cache_read_input_tokens = 800
        resp.usage.cache_creation_input_tokens = 200
        client = _make_mock_client(resp)
        llm.init(client=client, model="m")

        await llm.ask("hello")
        assert llm.get_cache_usage() == (800, 200)


class TestEstimateCost:
    def test_known_model_no_cache(self):
        """Cost for a known model with no cache tokens."""
        cost = llm.estimate_cost("claude-sonnet-4-5-20250929", 1_000_000, 100_000)
        assert cost is not None
        # 1M in * $3/M + 100k out * $15/M = $3 + $1.5 = $4.5
        assert cost == pytest.approx(4.5)

    def test_unknown_model_returns_none(self):
        cost = llm.estimate_cost("unknown-model", 1000, 500)
        assert cost is None

    def test_cache_read_tokens(self):
        """Cache reads cost 10% of input rate."""
        cost = llm.estimate_cost(
            "claude-sonnet-4-5-20250929",
            input_tokens=0, output_tokens=0,
            cache_read_tokens=1_000_000,
        )
        assert cost is not None
        # 1M cache_read * $3/M * 0.1 = $0.30
        assert cost == pytest.approx(0.30)

    def test_cache_creation_tokens(self):
        """Cache writes cost 125% of input rate."""
        cost = llm.estimate_cost(
            "claude-sonnet-4-5-20250929",
            input_tokens=0, output_tokens=0,
            cache_creation_tokens=1_000_000,
        )
        assert cost is not None
        # 1M cache_create * $3/M * 1.25 = $3.75
        assert cost == pytest.approx(3.75)

    def test_all_token_types(self):
        """Full cost with all four token categories."""
        cost = llm.estimate_cost(
            "claude-sonnet-4-5-20250929",
            input_tokens=100_000,
            output_tokens=50_000,
            cache_read_tokens=800_000,
            cache_creation_tokens=200_000,
        )
        assert cost is not None
        # 100k * 3/M + 800k * 0.3/M + 200k * 3.75/M + 50k * 15/M
        # = 0.30 + 0.24 + 0.75 + 0.75 = 2.04
        assert cost == pytest.approx(2.04)

    def test_haiku_pricing(self):
        cost = llm.estimate_cost(
            "claude-haiku-3-5-20241022",
            input_tokens=1_000_000, output_tokens=1_000_000,
        )
        assert cost is not None
        # 1M * $0.80/M + 1M * $4/M = $4.80
        assert cost == pytest.approx(4.80)

    @pytest.mark.asyncio
    async def test_record_usage_prints_cost(self, capsys: pytest.CaptureFixture[str]):
        """_record_usage appends per-call cost to the log line."""
        resp = _make_mock_response("a", input_tokens=1_000_000, output_tokens=100_000)
        resp.usage.cache_read_input_tokens = 0
        resp.usage.cache_creation_input_tokens = 0
        client = _make_mock_client(resp)
        llm.init(client=client, model="claude-sonnet-4-5-20250929")

        await llm.ask("hello", label="test_cost")
        # Cost: 1M*3/M + 100k*15/M = 3 + 1.5 = $4.5
        # The output goes to Rich console, check via capsys
        captured = capsys.readouterr()
        assert "$4.5000" in captured.out


class TestCacheControl:
    @pytest.mark.asyncio
    async def test_call_with_tools_cache_control(self):
        """_call_with_tools sets cache_control on last tool, first message, and tool_results."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "my_tool"
        tool_use_block.input = {"key": "val"}
        tool_use_block.id = "tu_1"

        tool_response = MagicMock()
        tool_response.content = [tool_use_block]
        tool_response.stop_reason = "tool_use"

        final_response = _make_mock_response("done")

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[tool_response, final_response])
        llm.init(client=client, model="m")

        tools = [
            {"name": "tool_a", "description": "a", "input_schema": {"type": "object"}},
            {"name": "tool_b", "description": "b", "input_schema": {"type": "object"}},
        ]
        executors: dict[str, Callable[[dict[str, Any]], str]] = {
            "my_tool": lambda inp: "result",
        }

        await llm.ask("prompt text", tools=tools, executors=executors)

        # Check first call (before tool execution)
        first_call_kwargs = client.messages.create.call_args_list[0].kwargs

        # Last tool should have cache_control
        last_tool = first_call_kwargs["tools"][-1]
        assert last_tool["cache_control"] == {"type": "ephemeral"}
        # First tool should NOT have cache_control
        first_tool = first_call_kwargs["tools"][0]
        assert "cache_control" not in first_tool

        # First user message content should be a list with cache_control
        first_msg = first_call_kwargs["messages"][0]
        assert isinstance(first_msg["content"], list)
        assert first_msg["content"][0]["type"] == "text"
        assert first_msg["content"][0]["text"] == "prompt text"
        assert first_msg["content"][0]["cache_control"] == {"type": "ephemeral"}

        # Check second call (after tool execution)
        second_call_kwargs = client.messages.create.call_args_list[1].kwargs
        # The user message with tool_results should have cache_control on the last block
        tool_result_msg = second_call_kwargs["messages"][-1]
        assert tool_result_msg["role"] == "user"
        last_block = tool_result_msg["content"][-1]
        assert last_block["type"] == "tool_result"
        assert last_block["cache_control"] == {"type": "ephemeral"}

    @pytest.mark.asyncio
    async def test_rolling_cache_cleans_previous_breakpoints(self):
        """Each iteration removes cache_control from previous tool_results."""
        # Two rounds of tool use, then final text
        tool_block_1 = MagicMock()
        tool_block_1.type = "tool_use"
        tool_block_1.name = "t"
        tool_block_1.input = {}
        tool_block_1.id = "tu_1"

        tool_block_2 = MagicMock()
        tool_block_2.type = "tool_use"
        tool_block_2.name = "t"
        tool_block_2.input = {}
        tool_block_2.id = "tu_2"

        resp1 = MagicMock()
        resp1.content = [tool_block_1]
        resp1.stop_reason = "tool_use"

        resp2 = MagicMock()
        resp2.content = [tool_block_2]
        resp2.stop_reason = "tool_use"

        resp3 = _make_mock_response("final")

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[resp1, resp2, resp3])
        llm.init(client=client, model="m")

        tools = [{"name": "t", "description": "t", "input_schema": {"type": "object"}}]
        executors: dict[str, Callable[[dict[str, Any]], str]] = {"t": lambda inp: "ok"}

        await llm.ask("go", tools=tools, executors=executors)

        # On the third call, the first tool_result message should NOT have cache_control
        # (it was cleaned up), but the second one should.
        third_call_kwargs = client.messages.create.call_args_list[2].kwargs
        msgs = cast(list[dict[str, Any]], third_call_kwargs["messages"])

        # Find all user messages with tool_result content
        tool_result_msgs = [
            m for m in msgs
            if m.get("role") == "user"
            and isinstance(m.get("content"), list)
            and any(
                b.get("type") == "tool_result"
                for b in cast(list[dict[str, Any]], m["content"])
            )
        ]
        assert len(tool_result_msgs) == 2

        # First tool_result message: cache_control should be removed
        for block in cast(list[dict[str, Any]], tool_result_msgs[0]["content"]):
            if block.get("type") == "tool_result":
                assert "cache_control" not in block

        # Last tool_result message: cache_control should be present
        last_block = cast(list[dict[str, Any]], tool_result_msgs[1]["content"])[-1]
        assert last_block["cache_control"] == {"type": "ephemeral"}


class TestResponseModel:
    @pytest.mark.asyncio
    async def test_valid_json_returns_model(self):
        """Valid JSON response is parsed and returned as a Pydantic model."""
        client = _make_mock_client(_make_mock_response('{"useful": true, "name": "search"}'))
        llm.init(client=client, model="m")

        result = await llm.ask("test", response_model=_SampleModel)
        assert isinstance(result, _SampleModel)
        assert result.useful is True
        assert result.name == "search"

    @pytest.mark.asyncio
    async def test_json_in_markdown_fences(self):
        """JSON wrapped in markdown fences is extracted and parsed."""
        text = '```json\n{"useful": false}\n```'
        client = _make_mock_client(_make_mock_response(text))
        llm.init(client=client, model="m")

        result = await llm.ask("test", response_model=_SampleModel)
        assert result.useful is False

    @pytest.mark.asyncio
    async def test_invalid_then_valid_retries(self):
        """Invalid first response triggers retry; valid retry succeeds."""
        bad_resp = _make_mock_response("not json at all")
        good_resp = _make_mock_response('{"useful": true, "name": "retry_ok"}')
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[bad_resp, good_resp])
        llm.init(client=client, model="m")

        result = await llm.ask("test", response_model=_SampleModel)
        assert isinstance(result, _SampleModel)
        assert result.name == "retry_ok"
        assert client.messages.create.await_count == 2

    @pytest.mark.asyncio
    async def test_invalid_after_retry_raises(self):
        """Both attempts invalid → raises an error."""
        bad1 = _make_mock_response("nope")
        bad2 = _make_mock_response("still nope")
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[bad1, bad2])
        llm.init(client=client, model="m")

        with pytest.raises((ValueError, Exception)):
            await llm.ask("test", response_model=_SampleModel)

    @pytest.mark.asyncio
    async def test_validation_error_retries(self):
        """JSON parses but fails Pydantic validation → retry with error message."""
        # useful must be bool, not string
        bad_resp = _make_mock_response('{"useful": "not_a_bool"}')
        good_resp = _make_mock_response('{"useful": true}')
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[bad_resp, good_resp])
        llm.init(client=client, model="m")

        result = await llm.ask("test", response_model=_SampleModel)
        assert result.useful is True

    @pytest.mark.asyncio
    async def test_prompt_appended_with_json_instruction(self):
        """When response_model is set, prompt gets JSON instruction appended."""
        client = _make_mock_client(_make_mock_response('{"useful": true}'))
        llm.init(client=client, model="m")

        await llm.ask("my prompt", response_model=_SampleModel)

        call_kwargs = client.messages.create.call_args.kwargs
        prompt_text = call_kwargs["messages"][0]["content"]
        assert "IMPORTANT: Respond with a single minified JSON" in prompt_text
        assert "my prompt" in prompt_text

    @pytest.mark.asyncio
    async def test_with_tools_and_response_model(self):
        """response_model works with tool-use path too."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "my_tool"
        tool_use_block.input = {}
        tool_use_block.id = "tu_1"

        tool_response = MagicMock()
        tool_response.content = [tool_use_block]
        tool_response.stop_reason = "tool_use"

        final_response = _make_mock_response('{"useful": true, "name": "found"}')

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[tool_response, final_response])
        llm.init(client=client, model="m")

        tools = [{"name": "my_tool", "description": "test", "input_schema": {"type": "object"}}]
        executors: dict[str, Callable[[dict[str, Any]], str]] = {"my_tool": lambda inp: "ok"}

        result = await llm.ask(
            "test", tools=tools, executors=executors, response_model=_SampleModel,
        )
        assert isinstance(result, _SampleModel)
        assert result.name == "found"
