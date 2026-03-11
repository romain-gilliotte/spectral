"""Tests for the centralized LLM helper (cli/helpers/llm/)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest

import cli.helpers.llm as llm
from cli.helpers.llm import (
    _debug as _debug_mod,  # pyright: ignore[reportPrivateUsage]
)
from cli.helpers.llm._client import set_test_model


class _SampleModel(BaseModel):
    useful: bool
    name: str | None = None


def _text_model(text: str) -> FunctionModel:
    """Create a FunctionModel that always returns the given text."""
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
    return FunctionModel(model_fn)


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
        set_test_model(_text_model("the answer"))
        conv = llm.Conversation()
        result = await conv.ask_text("what is 1+1?")
        assert result == "the answer"

    @pytest.mark.asyncio
    async def test_uses_configured_model(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from cli.formats.config import Config
        from cli.helpers.storage import write_config

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        write_config(Config(api_key="sk-ant-test", model="claude-test-123"))
        set_test_model(_text_model("ok"))
        conv = llm.Conversation()
        assert conv._model == "claude-test-123"
        await conv.ask_text("hello")

    @pytest.mark.asyncio
    async def test_no_system_works(self):
        set_test_model(_text_model("ok"))
        conv = llm.Conversation()
        result = await conv.ask_text("hello")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_system_string(self):
        set_test_model(_text_model("ok"))
        conv = llm.Conversation(system="You are a helpful assistant.")
        result = await conv.ask_text("hello")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_system_list(self):
        set_test_model(_text_model("ok"))
        conv = llm.Conversation(system=["block1", "block2"])
        result = await conv.ask_text("hello")
        assert result == "ok"


class TestConversationAskJson:
    @pytest.mark.asyncio
    async def test_valid_json_returns_model(self):
        set_test_model(_text_model('{"useful": true, "name": "search"}'))
        conv = llm.Conversation()
        result = await conv.ask_json("test", _SampleModel)
        assert isinstance(result, _SampleModel)
        assert result.useful is True
        assert result.name == "search"

    @pytest.mark.asyncio
    async def test_optional_field(self):
        set_test_model(_text_model('{"useful": false}'))
        conv = llm.Conversation()
        result = await conv.ask_json("test", _SampleModel)
        assert isinstance(result, _SampleModel)
        assert result.useful is False
        assert result.name is None


class TestConversationDebug:
    @pytest.mark.asyncio
    async def test_writes_debug_file(self, tmp_path: Path):
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()
        llm.init_debug(debug=True, debug_dir=debug_dir)

        set_test_model(_text_model("debug test"))
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
        set_test_model(_text_model("a"))
        conv = llm.Conversation()
        await conv.ask_text("hello")

        with patch("cli.helpers.llm._cost.console") as mock_console:
            llm.print_usage_summary()
            mock_console.print.assert_called_once()
            call_str = mock_console.print.call_args[0][0]
            assert "input" in call_str
            assert "output" in call_str
