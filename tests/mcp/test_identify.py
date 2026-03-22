"""Tests for MCP identify capabilities (per-trace evaluation)."""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from cli.commands.mcp.identify import identify_capabilities
from cli.formats.mcp_tool import ToolDefinition, ToolRequest
from cli.helpers.llm.providers.testing import set_test_model
from tests.conftest import make_trace


def _extract_user_prompt(messages: list[Any]) -> str:
    """Extract the last user prompt text from PydanticAI messages."""
    for msg in reversed(messages):
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    return str(part.content)
    return ""


def _extract_system_text(messages: list[Any]) -> str:
    """Extract concatenated system prompt text from messages."""
    from pydantic_ai.messages import SystemPromptPart

    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, SystemPromptPart):
                    parts.append(part.content)
    return " ".join(parts)


def _setup_llm(response_text: str) -> None:
    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        if info.output_tools:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args=response_text,
                    tool_call_id="tc_result",
                ),
            ])
        return ModelResponse(parts=[TextPart(content=response_text)])
    set_test_model(FunctionModel(model_fn))


def test_identify_returns_candidate_when_useful() -> None:
    _setup_llm(json.dumps({
        "useful": True,
        "name": "search_routes",
        "description": "Search for train routes",
    }))

    target = make_trace("t_0001", "POST", "https://api.example.com/search", 200, 1000)

    result = identify_capabilities(
        target_trace=target,
        existing_tools=[],
        system_context="\U0001f310 t_0001: POST /search \u2192 200",
    )

    assert result is not None
    assert result.name == "search_routes"
    assert result.description == "Search for train routes"
    assert result.trace_ids == ["t_0001"]


def test_identify_returns_none_when_not_useful() -> None:
    _setup_llm(json.dumps({"useful": False}))

    target = make_trace("t_0001", "GET", "https://cdn.example.com/font.woff", 200, 1000)
    result = identify_capabilities(
        target_trace=target,
        existing_tools=[],
        system_context="",
    )

    assert result is None


def test_identify_returns_none_on_malformed_response() -> None:
    """When LLM returns useful: false with minimal JSON, step returns None."""
    _setup_llm(json.dumps({"useful": False, "name": None, "description": None}))

    target = make_trace("t_0001", "GET", "https://cdn.example.com/font.woff", 200, 1000)
    result = identify_capabilities(
        target_trace=target,
        existing_tools=[],
        system_context="",
    )

    assert result is None


def test_identify_no_tools_in_llm_call() -> None:
    """Verify that the identify step does NOT pass investigation tools to the LLM."""
    captured_info: list[AgentInfo] = []

    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        captured_info.append(info)
        text = json.dumps({"useful": False})
        if info.output_tools:
            return ModelResponse(parts=[
                ToolCallPart(tool_name=info.output_tools[0].name, args=text, tool_call_id="tc"),
            ])
        return ModelResponse(parts=[TextPart(content=text)])

    set_test_model(FunctionModel(model_fn))

    target = make_trace("t_0001", "GET", "https://api.example.com/data", 200, 1000)
    identify_capabilities(
        target_trace=target,
        existing_tools=[],
        system_context="",
    )

    assert len(captured_info) == 1
    # Only the result tool should be present, no investigation tools
    assert len(captured_info[0].function_tools) == 0


def test_identify_shows_existing_tools() -> None:
    """Verify that existing tools are mentioned in the user prompt."""
    captured_prompts: list[str] = []

    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        captured_prompts.append(_extract_user_prompt(messages))
        text = json.dumps({"useful": False})
        if info.output_tools:
            return ModelResponse(parts=[
                ToolCallPart(tool_name=info.output_tools[0].name, args=text, tool_call_id="tc"),
            ])
        return ModelResponse(parts=[TextPart(content=text)])

    set_test_model(FunctionModel(model_fn))

    existing = [
        ToolDefinition(
            name="search_routes",
            description="Search for routes",
            parameters={"type": "object", "properties": {}},
            request=ToolRequest(method="POST", url="https://api.example.com/api/search"),
        ),
    ]

    target = make_trace("t_0003", "GET", "https://api.example.com/account", 200, 3000)
    identify_capabilities(
        target_trace=target,
        existing_tools=existing,
        system_context="",
    )

    assert captured_prompts
    prompt = captured_prompts[0]
    assert "search_routes" in prompt
    assert "do NOT duplicate" in prompt


def test_identify_shows_request_details_inline() -> None:
    """Verify that target trace request details are shown inline in the prompt."""
    captured_prompts: list[str] = []

    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        captured_prompts.append(_extract_user_prompt(messages))
        text = json.dumps({"useful": False})
        if info.output_tools:
            return ModelResponse(parts=[
                ToolCallPart(tool_name=info.output_tools[0].name, args=text, tool_call_id="tc"),
            ])
        return ModelResponse(parts=[TextPart(content=text)])

    set_test_model(FunctionModel(model_fn))

    target = make_trace(
        "t_0001", "POST", "https://api.example.com/api/search", 200, 1000,
        request_body=json.dumps({"origin": "Paris", "destination": "Lyon"}).encode(),
    )
    identify_capabilities(
        target_trace=target,
        existing_tools=[],
        system_context="",
    )

    assert captured_prompts
    prompt = captured_prompts[0]
    assert "t_0001" in prompt
    assert "POST" in prompt
    assert "api.example.com" in prompt
    assert "Paris" in prompt
    assert "Lyon" in prompt


def test_identify_includes_timeline_in_system() -> None:
    """Verify that the timeline text is included in the system prompt."""
    captured_systems: list[str] = []

    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        captured_systems.append(_extract_system_text(messages))
        text = json.dumps({"useful": False})
        if info.output_tools:
            return ModelResponse(parts=[
                ToolCallPart(tool_name=info.output_tools[0].name, args=text, tool_call_id="tc"),
            ])
        return ModelResponse(parts=[TextPart(content=text)])

    set_test_model(FunctionModel(model_fn))

    timeline = (
        '\U0001f5b1 [click] "Search" on https://example.com/home\n'
        "\U0001f310 t_0001: POST /search \u2192 200 (application/json 15B)"
    )

    target = make_trace("t_0001", "POST", "https://api.example.com/api/search", 200, 1000)
    identify_capabilities(
        target_trace=target,
        existing_tools=[],
        system_context=timeline,
    )

    assert captured_systems
    system_text = captured_systems[0]
    assert "\U0001f310" in system_text
    assert "\U0001f5b1" in system_text
    assert "/search" in system_text
    assert "[click]" in system_text
    assert '"Search"' in system_text
