"""Tests for MCP trace cleanup step."""

from __future__ import annotations

import json

from cli.commands.analyze.steps.mcp.cleanup import CleanupTracesStep
from cli.commands.analyze.steps.mcp.types import CleanupInput
from cli.formats.mcp_tool import ToolDefinition, ToolRequest
from tests.conftest import make_trace


def _make_tool(method: str, path: str, body: dict | None = None) -> ToolDefinition:
    return ToolDefinition(
        name="test_tool",
        description="Test",
        parameters={"type": "object", "properties": {}},
        request=ToolRequest(method=method, path=path, body=body),
    )


async def test_removes_matching_traces() -> None:
    tool = _make_tool("POST", "/api/search", body={"currency": "EUR", "origin": {"$param": "origin"}})
    traces = [
        make_trace(
            "t_0001", "POST", "https://api.example.com/api/search", 200, 1000,
            request_body=json.dumps({"currency": "EUR", "origin": "Paris"}).encode(),
        ),
        make_trace(
            "t_0002", "POST", "https://api.example.com/api/search", 200, 2000,
            request_body=json.dumps({"currency": "EUR", "origin": "Lyon"}).encode(),
        ),
        make_trace(
            "t_0003", "GET", "https://api.example.com/api/users", 200, 3000,
        ),
    ]

    step = CleanupTracesStep()
    remaining = await step.run(CleanupInput(
        traces=traces,
        tool_definition=tool,
        base_url="https://api.example.com",
    ))

    assert len(remaining) == 1
    assert remaining[0].meta.id == "t_0003"


async def test_keeps_different_method() -> None:
    tool = _make_tool("POST", "/api/data")
    traces = [
        make_trace("t_0001", "GET", "https://api.example.com/api/data", 200, 1000),
    ]

    step = CleanupTracesStep()
    remaining = await step.run(CleanupInput(
        traces=traces, tool_definition=tool, base_url="https://api.example.com",
    ))
    assert len(remaining) == 1


async def test_path_params_match() -> None:
    tool = _make_tool("GET", "/api/users/{user_id}")
    traces = [
        make_trace("t_0001", "GET", "https://api.example.com/api/users/123", 200, 1000),
        make_trace("t_0002", "GET", "https://api.example.com/api/users/456", 200, 2000),
        make_trace("t_0003", "GET", "https://api.example.com/api/orders", 200, 3000),
    ]

    step = CleanupTracesStep()
    remaining = await step.run(CleanupInput(
        traces=traces, tool_definition=tool, base_url="https://api.example.com",
    ))
    assert len(remaining) == 1
    assert remaining[0].meta.id == "t_0003"


async def test_fixed_body_mismatch_keeps_trace() -> None:
    tool = _make_tool("POST", "/api/data", body={"type": "search", "q": {"$param": "query"}})
    traces = [
        make_trace(
            "t_0001", "POST", "https://api.example.com/api/data", 200, 1000,
            request_body=json.dumps({"type": "search", "q": "hello"}).encode(),
        ),
        make_trace(
            "t_0002", "POST", "https://api.example.com/api/data", 200, 2000,
            request_body=json.dumps({"type": "update", "q": "world"}).encode(),
        ),
    ]

    step = CleanupTracesStep()
    remaining = await step.run(CleanupInput(
        traces=traces, tool_definition=tool, base_url="https://api.example.com",
    ))
    # t_0002 has type="update" which doesn't match fixed "search"
    assert len(remaining) == 1
    assert remaining[0].meta.id == "t_0002"
