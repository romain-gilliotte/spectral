"""Tests for MCP pipeline end-to-end with mocked LLM."""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from cli.commands.capture.types import CaptureBundle
from cli.commands.mcp.analyze import build_mcp_tools
from cli.formats.capture_bundle import (
    AppInfo,
    CaptureManifest,
    CaptureStats,
    Header,
    Timeline,
    TimelineEvent,
)
from cli.helpers.llm.providers.testing import set_test_model
from tests.conftest import make_context, make_trace


def _make_bundle() -> CaptureBundle:
    traces = [
        make_trace(
            "t_0001", "POST", "https://api.example.com/api/search", 200, 1000,
            request_body=json.dumps({"origin": "Paris", "destination": "Lyon", "currency": "EUR"}).encode(),
            response_body=b'{"results": []}',
            request_headers=[Header(name="Authorization", value="Bearer tok")],
        ),
        make_trace(
            "t_0002", "POST", "https://api.example.com/api/search", 200, 2000,
            request_body=json.dumps({"origin": "Lyon", "destination": "Marseille", "currency": "EUR"}).encode(),
            response_body=b'{"results": []}',
            request_headers=[Header(name="Authorization", value="Bearer tok")],
        ),
        make_trace(
            "t_0003", "GET", "https://api.example.com/api/account", 200, 4000,
            response_body=b'{"name": "Alice", "balance": 100}',
            request_headers=[Header(name="Authorization", value="Bearer tok")],
        ),
    ]
    contexts = [
        make_context("c_0001", 999, action="click", text="Search", page_url="https://www.example.com/search"),
        make_context("c_0002", 3999, action="click", text="Account", page_url="https://www.example.com/account"),
    ]
    manifest = CaptureManifest(
        capture_id="test-mcp",
        created_at="2026-01-01T00:00:00Z",
        app=AppInfo(name="Test", base_url="https://www.example.com", title="Test"),
        duration_ms=5000,
        stats=CaptureStats(trace_count=3, context_count=2),
    )
    timeline = Timeline(events=[
        TimelineEvent(timestamp=999, type="context", ref="c_0001"),
        TimelineEvent(timestamp=1000, type="trace", ref="t_0001"),
        TimelineEvent(timestamp=2000, type="trace", ref="t_0002"),
        TimelineEvent(timestamp=3999, type="context", ref="c_0002"),
        TimelineEvent(timestamp=4000, type="trace", ref="t_0003"),
    ])
    return CaptureBundle(
        manifest=manifest, traces=traces, contexts=contexts, timeline=timeline,
    )


def _extract_user_prompt(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    return str(part.content)
    return ""


def _extract_system_text(messages: list[Any]) -> str:
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, SystemPromptPart):
                    parts.append(part.content)
    return " ".join(parts)


def _setup_pipeline_llm() -> None:
    """Set up a FunctionModel that handles the greedy pipeline calls."""

    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        prompt = _extract_user_prompt(messages)
        system_text = _extract_system_text(messages)
        prompt_lower = prompt.lower()
        full_text_lower = (prompt + " " + system_text).lower()

        if "base url" in prompt_lower and "business api" in prompt_lower:
            text = json.dumps({"base_urls": ["https://api.example.com"]})
        elif "target trace: t_0001" in prompt_lower:
            text = json.dumps({
                "useful": True,
                "name": "search_routes",
                "description": "Search for train routes",
            })
        elif "candidate: search_routes" in prompt_lower:
            text = json.dumps({
                "tool": {
                    "name": "search_routes",
                    "description": "Search for train routes",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "origin": {"type": "string"},
                            "destination": {"type": "string"},
                        },
                        "required": ["origin", "destination"],
                    },
                    "request": {
                        "method": "POST",
                        "url": "https://api.example.com/api/search",
                        "body": {
                            "origin": {"$param": "origin"},
                            "destination": {"$param": "destination"},
                            "currency": "EUR",
                        },
                    },
                },
                "consumed_trace_ids": ["t_0001", "t_0002"],
            })
        elif "target trace: t_0003" in prompt_lower:
            text = json.dumps({
                "useful": True,
                "name": "get_account",
                "description": "Get account information",
            })
        elif "candidate: get_account" in prompt_lower:
            text = json.dumps({
                "tool": {
                    "name": "get_account",
                    "description": "Get account info",
                    "parameters": {"type": "object", "properties": {}},
                    "request": {"method": "GET", "url": "https://api.example.com/api/account"},
                },
                "consumed_trace_ids": ["t_0003"],
            })
        elif "business capability" in full_text_lower:
            text = json.dumps({"useful": False})
        else:
            text = json.dumps({"useful": False})

        if info.output_tools:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args=text,
                    tool_call_id="tc_result",
                ),
            ])
        return ModelResponse(parts=[TextPart(content=text)])

    set_test_model(FunctionModel(model_fn))


def test_pipeline_extracts_tools() -> None:
    _setup_pipeline_llm()
    bundle = _make_bundle()

    tools = build_mcp_tools(bundle, "testapp")

    assert len(tools) >= 1
    tool_names = {t.name for t in tools}
    assert "search_routes" in tool_names
    # URLs should be absolute after pipeline processing
    for tool in tools:
        assert tool.request.url.startswith("https://")
