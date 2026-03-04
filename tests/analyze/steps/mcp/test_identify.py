"""Tests for MCP identify capabilities step (batch mode)."""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import MagicMock

from cli.commands.analyze.steps.mcp.identify import IdentifyCapabilitiesStep
from cli.commands.analyze.steps.mcp.types import IdentifyInput
from cli.commands.analyze.steps.types import Correlation
import cli.helpers.llm as llm
from tests.conftest import make_context, make_trace


def _setup_llm(response_text: str) -> None:
    mock_client = MagicMock()

    async def mock_create(**kwargs: object) -> MagicMock:
        resp = MagicMock()
        content_block = MagicMock()
        content_block.type = "text"
        content_block.text = response_text
        resp.content = [content_block]
        resp.stop_reason = "end_turn"
        return resp

    mock_client.messages.create = mock_create
    llm.init(client=mock_client, model="test")


async def test_identify_returns_candidates() -> None:
    _setup_llm(json.dumps([
        {
            "name": "search_routes",
            "description": "Search for train routes",
            "trace_ids": ["t_0001", "t_0002"],
        },
        {
            "name": "get_account",
            "description": "Get account info",
            "trace_ids": ["t_0003"],
        },
    ]))

    traces = [
        make_trace("t_0001", "POST", "https://api.example.com/search", 200, 1000),
        make_trace("t_0002", "POST", "https://api.example.com/search", 200, 2000),
        make_trace("t_0003", "GET", "https://api.example.com/account", 200, 3000),
    ]
    ctx = make_context("c_0001", 999)
    correlations = [Correlation(context=ctx, traces=traces[:2])]

    step = IdentifyCapabilitiesStep()
    result = await step.run(IdentifyInput(
        correlations=correlations,
        remaining_traces=traces,
        base_url="https://api.example.com",
    ))

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0].name == "search_routes"
    assert result[0].trace_ids == ["t_0001", "t_0002"]
    assert result[1].name == "get_account"


async def test_identify_returns_empty_on_stop() -> None:
    _setup_llm("[]")

    traces = [
        make_trace("t_0001", "GET", "https://cdn.example.com/font.woff", 200, 1000),
    ]
    step = IdentifyCapabilitiesStep()
    result = await step.run(IdentifyInput(
        correlations=[],
        remaining_traces=traces,
        base_url="https://cdn.example.com",
    ))

    assert result == []


async def test_identify_returns_empty_on_stop_object() -> None:
    _setup_llm(json.dumps({"stop": True}))

    traces = [
        make_trace("t_0001", "GET", "https://cdn.example.com/font.woff", 200, 1000),
    ]
    step = IdentifyCapabilitiesStep()
    result = await step.run(IdentifyInput(
        correlations=[],
        remaining_traces=traces,
        base_url="https://cdn.example.com",
    ))

    assert result == []


async def test_identify_no_tools_in_llm_call() -> None:
    """Verify that the batch identify step does NOT use investigation tools."""
    captured_kwargs: list[dict[str, Any]] = []

    mock_client = MagicMock()

    async def mock_create(**kwargs: Any) -> MagicMock:
        captured_kwargs.append(dict(kwargs))
        resp = MagicMock()
        content_block = MagicMock()
        content_block.type = "text"
        content_block.text = "[]"
        resp.content = [content_block]
        resp.stop_reason = "end_turn"
        return resp

    mock_client.messages.create = mock_create
    llm.init(client=mock_client, model="test")

    traces = [
        make_trace("t_0001", "GET", "https://api.example.com/data", 200, 1000),
    ]
    step = IdentifyCapabilitiesStep()
    await step.run(IdentifyInput(
        correlations=[],
        remaining_traces=traces,
        base_url="https://api.example.com",
    ))

    assert len(captured_kwargs) == 1
    # No tools should be passed to the LLM
    assert "tools" not in captured_kwargs[0] or captured_kwargs[0]["tools"] is None


async def test_identify_handles_single_object_response() -> None:
    """LLM might return a single object instead of an array."""
    _setup_llm(json.dumps({
        "name": "search_routes",
        "description": "Search for routes",
        "trace_ids": ["t_0001"],
    }))

    traces = [
        make_trace("t_0001", "POST", "https://api.example.com/search", 200, 1000),
    ]
    step = IdentifyCapabilitiesStep()
    result = await step.run(IdentifyInput(
        correlations=[],
        remaining_traces=traces,
        base_url="https://api.example.com",
    ))

    assert len(result) == 1
    assert result[0].name == "search_routes"


async def test_identify_enriched_trace_lines() -> None:
    """Verify that trace summaries include content-type and body size."""
    captured_prompt: list[str] = []

    mock_client = MagicMock()

    async def mock_create(**kwargs: Any) -> MagicMock:
        messages = cast(list[dict[str, str]], kwargs.get("messages", []))
        if messages:
            captured_prompt.append(str(messages[0].get("content", "")))
        resp = MagicMock()
        content_block = MagicMock()
        content_block.type = "text"
        content_block.text = "[]"
        resp.content = [content_block]
        resp.stop_reason = "end_turn"
        return resp

    mock_client.messages.create = mock_create
    llm.init(client=mock_client, model="test")

    from cli.formats.capture_bundle import Header

    traces = [
        make_trace(
            "t_0001", "POST", "https://api.example.com/api/search", 200, 1000,
            response_body=b'{"results": []}',
            response_headers=[Header(name="Content-Type", value="application/json; charset=utf-8")],
        ),
    ]
    step = IdentifyCapabilitiesStep()
    await step.run(IdentifyInput(
        correlations=[],
        remaining_traces=traces,
        base_url="https://api.example.com/api",
    ))

    assert captured_prompt
    prompt = captured_prompt[0]
    # Should show relative path (stripped base URL)
    assert "/search" in prompt
    # Should show content type
    assert "application/json" in prompt
    # Should show body size
    assert "15B" in prompt
