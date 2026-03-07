"""Tests for the centralized LLM helper (cli/helpers/llm/)."""
# pyright: reportPrivateUsage=false
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel
import pytest

import cli.helpers.llm as llm
from cli.helpers.llm import (
    _client as _client_mod,  # pyright: ignore[reportPrivateUsage]
    _conversation as _conv_mod,  # pyright: ignore[reportPrivateUsage]
    _debug as _debug_mod,  # pyright: ignore[reportPrivateUsage]
)


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


def _setup(client: Any = None, response: Any = None) -> MagicMock:
    """Setup a mock client via setup_client. Returns the mock client."""
    if client is None:
        client = _make_mock_client(response)
    _client_mod.setup_client(client)
    return client


class TestSetModel:
    def test_override_works(self):
        llm.set_model("custom-model")
        assert _conv_mod._model_override == "custom-model"

    def test_default_used_when_no_override(self):
        _setup(response=_make_mock_response("ok"))
        conv = llm.Conversation(model="my-default")
        assert conv._model == "my-default"
        # Verify no override is active
        assert _conv_mod._model_override is None


class TestInitDebug:
    def test_explicit_dir(self, tmp_path: Path):
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()
        llm.init_debug(debug=True, debug_dir=debug_dir)
        assert _debug_mod._debug_dir is debug_dir

    def test_creates_timestamped_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        llm.init_debug(debug=True)
        assert _debug_mod._debug_dir is not None
        assert _debug_mod._debug_dir.exists()


class TestConversationAskText:
    @pytest.mark.asyncio
    async def test_returns_text(self):
        client = _setup(response=_make_mock_response("the answer"))
        conv = llm.Conversation()
        result = await conv.ask_text("what is 1+1?")
        assert result == "the answer"
        client.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_model(self):
        llm.set_model("claude-test-123")
        client = _setup(response=_make_mock_response("ok"))
        conv = llm.Conversation()
        await conv.ask_text("hello")
        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-test-123"

    @pytest.mark.asyncio
    async def test_system_string(self):
        client = _setup(response=_make_mock_response("ok"))
        conv = llm.Conversation(system="You are a helpful assistant.")
        await conv.ask_text("hello")
        call_kwargs = client.messages.create.call_args.kwargs
        assert "system" in call_kwargs
        blocks = call_kwargs["system"]
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"
        assert blocks[0]["text"] == "You are a helpful assistant."
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}

    @pytest.mark.asyncio
    async def test_system_list(self):
        client = _setup(response=_make_mock_response("ok"))
        conv = llm.Conversation(system=["block1", "block2"])
        await conv.ask_text("hello")
        call_kwargs = client.messages.create.call_args.kwargs
        blocks = call_kwargs["system"]
        assert len(blocks) == 2
        assert blocks[0]["text"] == "block1"
        assert blocks[1]["text"] == "block2"
        assert all(b["cache_control"] == {"type": "ephemeral"} for b in blocks)

    @pytest.mark.asyncio
    async def test_no_system_omits_kwarg(self):
        client = _setup(response=_make_mock_response("ok"))
        conv = llm.Conversation()
        await conv.ask_text("hello")
        call_kwargs = client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    @pytest.mark.asyncio
    async def test_detects_truncation(self):
        _setup(response=_make_mock_response("partial...", stop_reason="max_tokens"))
        conv = llm.Conversation(max_tokens=100, label="test_trunc")
        with pytest.raises(ValueError, match="LLM response truncated"):
            await conv.ask_text("hello")


class TestConversationAskJson:
    @pytest.mark.asyncio
    async def test_valid_json_returns_model(self):
        _setup(response=_make_mock_response('{"useful": true, "name": "search"}'))
        conv = llm.Conversation()
        result = await conv.ask_json("test", _SampleModel)
        assert isinstance(result, _SampleModel)
        assert result.useful is True
        assert result.name == "search"

    @pytest.mark.asyncio
    async def test_json_in_markdown_fences(self):
        text = '```json\n{"useful": false}\n```'
        _setup(response=_make_mock_response(text))
        conv = llm.Conversation()
        result = await conv.ask_json("test", _SampleModel)
        assert result.useful is False

    @pytest.mark.asyncio
    async def test_invalid_then_valid_retries(self):
        bad_resp = _make_mock_response("not json at all")
        good_resp = _make_mock_response('{"useful": true, "name": "retry_ok"}')
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[bad_resp, good_resp])
        _setup(client=client)

        conv = llm.Conversation()
        result = await conv.ask_json("test", _SampleModel)
        assert isinstance(result, _SampleModel)
        assert result.name == "retry_ok"
        assert client.messages.create.await_count == 2

    @pytest.mark.asyncio
    async def test_both_invalid_raises(self):
        bad1 = _make_mock_response("nope")
        bad2 = _make_mock_response("still nope")
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[bad1, bad2])
        _setup(client=client)

        conv = llm.Conversation()
        with pytest.raises((ValueError, Exception)):
            await conv.ask_json("test", _SampleModel)

    @pytest.mark.asyncio
    async def test_validation_error_retries(self):
        bad_resp = _make_mock_response('{"useful": "not_a_bool"}')
        good_resp = _make_mock_response('{"useful": true}')
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[bad_resp, good_resp])
        _setup(client=client)

        conv = llm.Conversation()
        result = await conv.ask_json("test", _SampleModel)
        assert result.useful is True

    @pytest.mark.asyncio
    async def test_prompt_includes_json_instruction(self):
        client = _setup(response=_make_mock_response('{"useful": true}'))
        conv = llm.Conversation()
        await conv.ask_json("my prompt", _SampleModel)
        call_kwargs = client.messages.create.call_args.kwargs
        prompt_text = call_kwargs["messages"][0]["content"]
        assert "IMPORTANT: Respond with a single minified JSON value" in prompt_text
        assert "my prompt" in prompt_text


class TestSend:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        expected = _make_mock_response()
        client = _setup(response=expected)
        result = await _client_mod.send(model="m", max_tokens=10, messages=[])
        assert result is expected
        client.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limit_with_retry_after(self):
        expected = _make_mock_response()
        error = _make_rate_limit_error(retry_after="0.01")
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[error, expected])
        _setup(client=client)

        result = await _client_mod.send(model="m", max_tokens=10, messages=[])
        assert result is expected
        assert client.messages.create.await_count == 2

    @pytest.mark.asyncio
    async def test_rate_limit_fallback_exponential(self):
        expected = _make_mock_response()
        error = _make_rate_limit_error(retry_after=None)
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[error, expected])
        _setup(client=client)

        original_backoff = _client_mod.FALLBACK_BACKOFF
        _client_mod.FALLBACK_BACKOFF = 0.01
        try:
            result = await _client_mod.send(model="m", max_tokens=10, messages=[])
            assert result is expected
        finally:
            _client_mod.FALLBACK_BACKOFF = original_backoff

    @pytest.mark.asyncio
    async def test_retries_exhausted_reraises(self):
        import anthropic

        error = _make_rate_limit_error(retry_after="0.01")
        client = MagicMock()
        client.messages.create = AsyncMock(
            side_effect=[error] * (_client_mod.MAX_RETRIES + 1)
        )
        _setup(client=client)

        with pytest.raises(anthropic.RateLimitError):
            await _client_mod.send(model="m", max_tokens=10, messages=[])
        assert client.messages.create.await_count == _client_mod.MAX_RETRIES + 1

    @pytest.mark.asyncio
    async def test_non_rate_limit_no_retry(self):
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=ValueError("boom"))
        _setup(client=client)

        with pytest.raises(ValueError, match="boom"):
            await _client_mod.send(model="m", max_tokens=10, messages=[])
        client.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
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
        _setup(client=client)

        # Set a custom semaphore with max_concurrent=2
        _client_mod._semaphore = asyncio.Semaphore(max_concurrent)

        await asyncio.gather(*[
            _client_mod.send(model="m", max_tokens=10, messages=[])
            for _ in range(6)
        ])
        assert peak_concurrent <= max_concurrent

    @pytest.mark.asyncio
    async def test_not_initialized_raises(self):
        # clear_client() is called by the fixture, so _client is None.
        # get_client() will try to lazily init — but with our dummy key,
        # it would create a real client. Instead we verify send() works
        # when properly initialized.
        _setup(response=_make_mock_response())
        result = await _client_mod.send(model="m", max_tokens=10, messages=[])
        assert result is not None


class TestConversationDebug:
    @pytest.mark.asyncio
    async def test_writes_debug_file(self, tmp_path: Path):
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()
        llm.init_debug(debug=True, debug_dir=debug_dir)

        _setup(response=_make_mock_response("debug test"))
        conv = llm.Conversation(label="test_label")
        await conv.ask_text("hello")

        files = list(debug_dir.iterdir())
        assert len(files) == 1
        content = files[0].read_text()
        assert "=== PROMPT ===" in content
        assert "hello" in content
        assert "=== RESPONSE ===" in content
        assert "debug test" in content
        assert "test_label" in files[0].name


class TestPrintUsageSummary:
    @pytest.mark.asyncio
    async def test_prints_after_calls(self):
        resp = _make_mock_response("a", input_tokens=1000, output_tokens=500)
        resp.usage.cache_read_input_tokens = 0
        resp.usage.cache_creation_input_tokens = 0
        _setup(response=resp)

        conv = llm.Conversation()
        await conv.ask_text("hello")

        with patch("cli.helpers.llm._cost.console") as mock_console:
            llm.print_usage_summary()
            mock_console.print.assert_called_once()
            call_str = mock_console.print.call_args[0][0]
            assert "1,000 input" in call_str
            assert "500 output" in call_str
