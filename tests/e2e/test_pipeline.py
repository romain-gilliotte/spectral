"""End-to-end pipeline tests: capture → analyze → MCP server.

Run with: ``uv run pytest tests/e2e/ --run-e2e -v``
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import time
from typing import Any

import pytest

from cli.formats.mcp_tool import TokenState
import cli.helpers.storage as storage

pytestmark = pytest.mark.e2e


# --------------------------------------------------------------------------- #
# Phase 1: Capture
# --------------------------------------------------------------------------- #

class TestCapture:
    def test_capture_stored(self, proxy_capture: str) -> None:
        caps = storage.list_captures(proxy_capture)
        assert len(caps) >= 1

    def test_capture_has_traces(self, proxy_capture: str) -> None:
        bundle = storage.load_app_bundle(proxy_capture)
        assert len(bundle.traces) >= 4  # auth + products + product/1 + order

        methods = {t.meta.request.method for t in bundle.traces}
        assert "GET" in methods
        assert "POST" in methods

        urls = [t.meta.request.url for t in bundle.traces]
        assert any("/api/products" in u for u in urls)
        assert any("/oauth/token" in u for u in urls)


# --------------------------------------------------------------------------- #
# Phase 2: Analyze (real LLM calls)
# --------------------------------------------------------------------------- #

class TestAnalyze:
    def test_tools_generated(self, analyzed_tools: list[Any]) -> None:
        assert len(analyzed_tools) >= 1

    def test_tools_have_valid_structure(self, analyzed_tools: list[Any]) -> None:
        for tool in analyzed_tools:
            assert tool.name
            assert tool.description
            assert tool.request.method in ("GET", "POST", "PUT", "DELETE", "PATCH")
            assert tool.request.url.startswith("http")
            assert tool.parameters.get("type") == "object"

    def test_tools_cover_endpoints(self, analyzed_tools: list[Any]) -> None:
        tool_urls = [t.request.url for t in analyzed_tools]
        assert any("product" in u.lower() for u in tool_urls)


# --------------------------------------------------------------------------- #
# Phase 3: MCP server (real HTTP calls to the Flask server)
# --------------------------------------------------------------------------- #

class TestMcpServer:
    @pytest.mark.asyncio
    async def test_list_tools(self, analyzed_tools: list[Any]) -> None:
        from mcp import types as mcp_types

        from cli.commands.mcp.server import _create_server

        server = _create_server()
        handler = server.request_handlers[mcp_types.ListToolsRequest]
        req = mcp_types.ListToolsRequest(method="tools/list")
        result = await handler(req)
        list_result: mcp_types.ListToolsResult = result.root  # type: ignore[assignment]
        assert len(list_result.tools) >= 1

    @pytest.mark.asyncio
    async def test_call_tool(
        self,
        analyzed_tools: list[Any],
        proxy_capture: str,
        flask_server: tuple[str, int],
    ) -> None:
        from cli.commands.mcp.server import _handle_call

        # Set auth token so the MCP server can authenticate against the Flask server
        storage.write_token(
            proxy_capture,
            TokenState(
                headers={"Authorization": "Bearer test-token-testuser"},
                obtained_at=time.time(),
            ),
        )

        # Find a GET tool (simplest to call without arguments)
        get_tools = [t for t in analyzed_tools if t.request.method == "GET"]
        assert get_tools, "Expected at least one GET tool"

        tool = get_tools[0]

        # Build minimal valid arguments from the tool's required parameters
        args: dict[str, Any] = {}
        required = tool.parameters.get("required", [])
        properties = tool.parameters.get("properties", {})
        for param in required:
            prop = properties.get(param, {})
            param_type = prop.get("type", "string")
            if param_type == "integer":
                args[param] = 1
            elif param_type == "number":
                args[param] = 1.0
            else:
                args[param] = "1"

        result = await _handle_call(proxy_capture, tool, args)
        assert "HTTP 200" in result or "HTTP 201" in result
