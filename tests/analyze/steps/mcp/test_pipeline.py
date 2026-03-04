"""Tests for MCP pipeline end-to-end with mocked LLM."""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import MagicMock

from cli.commands.analyze.steps.mcp.pipeline import build_mcp_tools
from cli.commands.capture.types import CaptureBundle
from cli.formats.capture_bundle import (
    AppInfo,
    CaptureManifest,
    CaptureStats,
    Header,
    Timeline,
    TimelineEvent,
)
import cli.helpers.llm as llm
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


def _setup_pipeline_llm() -> None:
    """Set up a mock LLM that handles the pipeline calls."""
    mock_client = MagicMock()

    async def mock_create(**kwargs: Any) -> MagicMock:
        resp = MagicMock()
        content_block = MagicMock()
        content_block.type = "text"
        resp.stop_reason = "end_turn"
        messages = cast(list[dict[str, Any]], kwargs.get("messages", []))

        # Extract the original prompt (first user message content)
        prompt = ""
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content", "")
                if isinstance(c, str):
                    prompt = c
                    break

        prompt_lower = prompt.lower()

        if "base url" in prompt_lower and "business api" in prompt_lower:
            content_block.text = json.dumps({"base_url": "https://api.example.com"})
        elif "analyze the authentication" in prompt_lower:
            content_block.text = json.dumps({
                "type": "bearer_token",
                "token_header": "Authorization",
                "token_prefix": "Bearer",
                "obtain_flow": "login_form",
            })
        elif "identify" in prompt_lower and "business capabilit" in prompt_lower:
            # Batch mode: return ALL candidates in one call
            content_block.text = json.dumps([
                {
                    "name": "search_routes",
                    "description": "Search for train routes",
                    "trace_ids": ["t_0001", "t_0002"],
                },
                {
                    "name": "get_account",
                    "description": "Get account information",
                    "trace_ids": ["t_0003"],
                },
            ])
        elif "building an mcp tool" in prompt_lower and "search_routes" in prompt:
            content_block.text = json.dumps({
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
                    "path": "/api/search",
                    "body": {
                        "origin": {"$param": "origin"},
                        "destination": {"$param": "destination"},
                        "currency": "EUR",
                    },
                },
            })
        elif "building an mcp tool" in prompt_lower and "get_account" in prompt:
            content_block.text = json.dumps({
                "name": "get_account",
                "description": "Get account info",
                "parameters": {"type": "object", "properties": {}},
                "request": {"method": "GET", "path": "/api/account"},
            })
        else:
            content_block.text = json.dumps({"stop": True})

        resp.content = [content_block]
        return resp

    mock_client.messages.create = mock_create
    llm.init(client=mock_client, model="test")


async def test_pipeline_extracts_tools() -> None:
    _setup_pipeline_llm()
    bundle = _make_bundle()

    result = await build_mcp_tools(bundle, "testapp")

    assert result.base_url == "https://api.example.com"
    assert len(result.tools) >= 1
    tool_names = {t.name for t in result.tools}
    assert "search_routes" in tool_names
    assert result.auth is not None


async def test_pipeline_progress_callback() -> None:
    _setup_pipeline_llm()
    bundle = _make_bundle()
    messages: list[str] = []

    await build_mcp_tools(bundle, "testapp", on_progress=messages.append)

    assert any("base url" in m.lower() for m in messages)
    assert any("tool" in m.lower() for m in messages)
    assert any("candidate" in m.lower() for m in messages)
