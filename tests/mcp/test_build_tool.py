"""Tests for MCP build tool."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from typing import Any

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest

from cli.commands.capture.types import CaptureBundle, Context, Trace
from cli.commands.mcp.build_tool import _collect_param_refs, build_tool
from cli.commands.mcp.types import ToolBuildInput, ToolCandidate
from cli.formats.capture_bundle import (
    AppInfo,
    CaptureManifest,
    CaptureStats,
    Timeline,
)
from cli.helpers.llm._client import set_test_model
from tests.conftest import make_trace


def _make_bundle(traces: list[Trace] | None = None, contexts: list[Context] | None = None) -> CaptureBundle:
    return CaptureBundle(
        manifest=CaptureManifest(
            capture_id="test",
            created_at="2026-01-01T00:00:00Z",
            app=AppInfo(name="T", base_url="http://localhost", title="T"),
            duration_ms=10000,
            stats=CaptureStats(),
        ),
        traces=traces or [],
        contexts=contexts or [],
        timeline=Timeline(),
    )


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


async def test_build_valid_tool() -> None:
    _setup_llm(json.dumps({
        "tool": {
            "name": "search_routes",
            "description": "Search for train routes",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "Departure city"},
                    "destination": {"type": "string", "description": "Arrival city"},
                },
                "required": ["origin", "destination"],
            },
            "request": {
                "method": "POST",
                "path": "/api/search",
                "body": {
                    "origin": {"$param": "origin"},
                    "destination": {"$param": "destination"},
                    "currency": "EUR",
                },
            },
        },
        "consumed_trace_ids": ["t_0001"],
    }))

    traces = [
        make_trace(
            "t_0001", "POST", "https://api.example.com/api/search", 200, 1000,
            request_body=json.dumps({"origin": "Paris", "destination": "Lyon", "currency": "EUR"}).encode(),
        ),
    ]

    result = await build_tool(ToolBuildInput(
        candidate=ToolCandidate("search_routes", "Search routes", ["t_0001"]),
        bundle=_make_bundle(traces=traces),
        base_url="https://api.example.com",
        existing_tools=[],
        system_context="",
    ))

    assert result.tool.name == "search_routes"
    assert result.tool.request.method == "POST"
    assert result.tool.request.body is not None
    assert result.tool.request.body["currency"] == "EUR"
    assert result.consumed_trace_ids == ["t_0001"]


async def test_build_tool_minimal_params() -> None:
    """Tool with minimal parameters is built correctly."""
    _setup_llm(json.dumps({
        "tool": {
            "name": "search_routes",
            "description": "Search for train routes",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string"},
                },
                "required": ["origin"],
            },
            "request": {
                "method": "POST",
                "path": "/api/search",
                "body": {"origin": {"$param": "origin"}},
            },
        },
        "consumed_trace_ids": ["t_0001"],
    }))

    traces = [
        make_trace("t_0001", "POST", "https://api.example.com/api/search", 200, 1000),
    ]

    result = await build_tool(ToolBuildInput(
        candidate=ToolCandidate("search_routes", "Search routes", ["t_0001"]),
        bundle=_make_bundle(traces=traces),
        base_url="https://api.example.com",
        existing_tools=[],
        system_context="",
    ))

    assert result.tool.name == "search_routes"
    assert result.consumed_trace_ids == ["t_0001"]


async def test_build_tool_with_path_params() -> None:
    _setup_llm(json.dumps({
        "tool": {
            "name": "get_user",
            "description": "Get a user by ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User ID"},
                },
                "required": ["user_id"],
            },
            "request": {
                "method": "GET",
                "path": "/api/users/{user_id}",
            },
        },
        "consumed_trace_ids": ["t_0001"],
    }))

    traces = [
        make_trace("t_0001", "GET", "https://api.example.com/api/users/123", 200, 1000),
    ]

    result = await build_tool(ToolBuildInput(
        candidate=ToolCandidate("get_user", "Get user", ["t_0001"]),
        bundle=_make_bundle(traces=traces),
        base_url="https://api.example.com",
        existing_tools=[],
        system_context="",
    ))

    assert result.tool.name == "get_user"
    assert "{user_id}" in result.tool.request.path


async def test_build_tool_validation_missing_param() -> None:
    # Path param not in parameters → validation error
    _setup_llm(json.dumps({
        "tool": {
            "name": "get_user",
            "description": "Get a user",
            "parameters": {"type": "object", "properties": {}},
            "request": {"method": "GET", "path": "/api/users/{user_id}"},
        },
        "consumed_trace_ids": ["t_0001"],
    }))

    traces = [make_trace("t_0001", "GET", "https://api.example.com/api/users/123", 200, 1000)]

    with pytest.raises(ValueError, match="Path params not in parameters"):
        await build_tool(ToolBuildInput(
            candidate=ToolCandidate("get_user", "Get user", ["t_0001"]),
            bundle=_make_bundle(traces=traces),
            base_url="https://api.example.com",
            existing_tools=[],
            system_context="",
        ))


class TestToolRequestHeaderValidation:
    def test_rejects_param_ref_in_headers(self) -> None:
        """ToolRequest.headers is dict[str, str] — $param dicts must be rejected."""
        from cli.formats.mcp_tool import ToolRequest

        with pytest.raises(Exception):
            ToolRequest.model_validate({
                "method": "GET",
                "path": "/api/cars",
                "headers": {"x-authorization": {"$param": "auth_token"}},
            })

    def test_accepts_literal_headers(self) -> None:
        from cli.formats.mcp_tool import ToolRequest

        req = ToolRequest.model_validate({
            "method": "GET",
            "path": "/api/cars",
            "headers": {"Accept": "application/json"},
        })
        assert req.headers == {"Accept": "application/json"}


class TestCollectParamRefs:
    def test_empty(self) -> None:
        assert _collect_param_refs(None) == set()

    def test_simple(self) -> None:
        body = {"a": {"$param": "origin"}, "b": "fixed"}
        assert _collect_param_refs(body) == {"origin"}

    def test_nested(self) -> None:
        body = {"data": {"name": {"$param": "name"}, "nested": {"x": {"$param": "x"}}}}
        assert _collect_param_refs(body) == {"name", "x"}

    def test_array(self) -> None:
        body = {"items": [{"val": {"$param": "v"}}]}
        assert _collect_param_refs(body) == {"v"}
