"""Tests for MCP identify capabilities (per-trace evaluation)."""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import MagicMock

from cli.commands.mcp.identify import identify_capabilities
from cli.commands.mcp.types import IdentifyInput
from cli.formats.mcp_tool import ToolDefinition, ToolRequest
import cli.helpers.llm as llm
from tests.conftest import make_trace


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


async def test_identify_returns_candidate_when_useful() -> None:
    _setup_llm(json.dumps({
        "useful": True,
        "name": "search_routes",
        "description": "Search for train routes",
    }))

    target = make_trace("t_0001", "POST", "https://api.example.com/search", 200, 1000)

    result = await identify_capabilities(IdentifyInput(
        remaining_traces=[target],
        base_url="https://api.example.com",
        target_trace=target,
        existing_tools=[],
        system_context="\U0001f310 t_0001: POST /search \u2192 200",
    ))

    assert result is not None
    assert result.name == "search_routes"
    assert result.description == "Search for train routes"
    assert result.trace_ids == ["t_0001"]


async def test_identify_returns_none_when_not_useful() -> None:
    _setup_llm(json.dumps({"useful": False}))

    target = make_trace("t_0001", "GET", "https://cdn.example.com/font.woff", 200, 1000)
    result = await identify_capabilities(IdentifyInput(
        remaining_traces=[target],
        base_url="https://cdn.example.com",
        target_trace=target,
        existing_tools=[],
        system_context="",
    ))

    assert result is None


async def test_identify_returns_none_on_malformed_response() -> None:
    """When LLM returns useful: false with minimal JSON, step returns None."""
    _setup_llm(json.dumps({"useful": False, "name": None, "description": None}))

    target = make_trace("t_0001", "GET", "https://cdn.example.com/font.woff", 200, 1000)
    result = await identify_capabilities(IdentifyInput(
        remaining_traces=[target],
        base_url="https://cdn.example.com",
        target_trace=target,
        existing_tools=[],
        system_context="",
    ))

    assert result is None


async def test_identify_no_tools_in_llm_call() -> None:
    """Verify that the identify step does NOT pass tools to the LLM (lightweight call)."""
    captured_kwargs: list[dict[str, Any]] = []

    mock_client = MagicMock()

    async def mock_create(**kwargs: Any) -> MagicMock:
        captured_kwargs.append(dict(kwargs))
        resp = MagicMock()
        content_block = MagicMock()
        content_block.type = "text"
        content_block.text = json.dumps({"useful": False})
        resp.content = [content_block]
        resp.stop_reason = "end_turn"
        return resp

    mock_client.messages.create = mock_create
    llm.init(client=mock_client, model="test")

    target = make_trace("t_0001", "GET", "https://api.example.com/data", 200, 1000)
    await identify_capabilities(IdentifyInput(
        remaining_traces=[target],
        base_url="https://api.example.com",
        target_trace=target,
        existing_tools=[],
        system_context="",
    ))

    assert len(captured_kwargs) == 1
    # Tools should NOT be passed (lightweight call)
    assert "tools" not in captured_kwargs[0]


async def test_identify_shows_existing_tools() -> None:
    """Verify that existing tools are mentioned in the user prompt."""
    captured_prompt: list[str] = []

    mock_client = MagicMock()

    async def mock_create(**kwargs: Any) -> MagicMock:
        messages = cast(list[dict[str, Any]], kwargs.get("messages", []))
        if messages:
            content = messages[0].get("content", "")
            if isinstance(content, str):
                captured_prompt.append(content)
        resp = MagicMock()
        content_block = MagicMock()
        content_block.type = "text"
        content_block.text = json.dumps({"useful": False})
        resp.content = [content_block]
        resp.stop_reason = "end_turn"
        return resp

    mock_client.messages.create = mock_create
    llm.init(client=mock_client, model="test")

    existing = [
        ToolDefinition(
            name="search_routes",
            description="Search for routes",
            parameters={"type": "object", "properties": {}},
            request=ToolRequest(method="POST", path="/api/search"),
        ),
    ]

    target = make_trace("t_0003", "GET", "https://api.example.com/account", 200, 3000)
    await identify_capabilities(IdentifyInput(
        remaining_traces=[target],
        base_url="https://api.example.com",
        target_trace=target,
        existing_tools=existing,
        system_context="",
    ))

    assert captured_prompt
    prompt = captured_prompt[0]
    assert "search_routes" in prompt
    assert "do NOT duplicate" in prompt


async def test_identify_shows_request_details_inline() -> None:
    """Verify that target trace request details are shown inline in the prompt."""
    captured_prompt: list[str] = []

    mock_client = MagicMock()

    async def mock_create(**kwargs: Any) -> MagicMock:
        messages = cast(list[dict[str, Any]], kwargs.get("messages", []))
        if messages:
            content = messages[0].get("content", "")
            if isinstance(content, str):
                captured_prompt.append(content)
        resp = MagicMock()
        content_block = MagicMock()
        content_block.type = "text"
        content_block.text = json.dumps({"useful": False})
        resp.content = [content_block]
        resp.stop_reason = "end_turn"
        return resp

    mock_client.messages.create = mock_create
    llm.init(client=mock_client, model="test")

    target = make_trace(
        "t_0001", "POST", "https://api.example.com/api/search", 200, 1000,
        request_body=json.dumps({"origin": "Paris", "destination": "Lyon"}).encode(),
    )
    await identify_capabilities(IdentifyInput(
        remaining_traces=[target],
        base_url="https://api.example.com",
        target_trace=target,
        existing_tools=[],
        system_context="",
    ))

    assert captured_prompt
    prompt = captured_prompt[0]
    assert "t_0001" in prompt
    assert "POST" in prompt
    assert "api.example.com" in prompt
    assert "Paris" in prompt
    assert "Lyon" in prompt


async def test_identify_includes_timeline_in_system() -> None:
    """Verify that the timeline text is included in the system blocks, not the user prompt."""
    captured_system: list[Any] = []

    mock_client = MagicMock()

    async def mock_create(**kwargs: Any) -> MagicMock:
        if "system" in kwargs:
            captured_system.append(kwargs["system"])
        resp = MagicMock()
        content_block = MagicMock()
        content_block.type = "text"
        content_block.text = json.dumps({"useful": False})
        resp.content = [content_block]
        resp.stop_reason = "end_turn"
        return resp

    mock_client.messages.create = mock_create
    llm.init(client=mock_client, model="test")

    timeline = (
        '\U0001f5b1 [click] "Search" on https://example.com/home\n'
        "\U0001f310 t_0001: POST /search \u2192 200 (application/json 15B)"
    )

    target = make_trace("t_0001", "POST", "https://api.example.com/api/search", 200, 1000)
    await identify_capabilities(IdentifyInput(
        remaining_traces=[target],
        base_url="https://api.example.com/api",
        target_trace=target,
        existing_tools=[],
        system_context=timeline,
    ))

    assert captured_system
    system_blocks = captured_system[0]
    # system_context is the first block
    system_text = system_blocks[0]["text"]
    assert "\U0001f310" in system_text
    assert "\U0001f5b1" in system_text
    assert "/search" in system_text
    assert "[click]" in system_text
    assert '"Search"' in system_text
