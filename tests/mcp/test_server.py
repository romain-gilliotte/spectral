"""Tests for MCP server."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

from mcp import types as mcp_types
import pytest

from cli.commands.mcp.server import (
    _apply_defaults,
    _build_registry,
    _create_server,
    _handle_call,
    _registry,
)
from cli.formats.mcp_tool import ToolDefinition, ToolRequest


def _make_tool(
    name: str = "search",
    method: str = "POST",
    path: str = "/api/search",
    requires_auth: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Test tool: {name}",
        parameters={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
        request=ToolRequest(method=method, path=path, body={"query": {"$param": "q"}}),
        requires_auth=requires_auth,
    )


class TestRegistry:
    def test_build_registry(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
        from cli.helpers.storage import ensure_app, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")

        tools = [_make_tool("search"), _make_tool("get_user", "GET", "/api/users/{user_id}")]
        write_tools("myapp", tools)

        _build_registry()

        assert "myapp_search" in _registry
        assert "myapp_get_user" in _registry
        assert _registry["myapp_search"][0] == "myapp"
        assert _registry["myapp_search"][1].name == "search"

    def test_registry_multiple_apps(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
        from cli.helpers.storage import ensure_app, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("app_a")
        ensure_app("app_b")

        write_tools("app_a", [_make_tool("search")])
        write_tools("app_b", [_make_tool("search")])

        _build_registry()

        assert "app_a_search" in _registry
        assert "app_b_search" in _registry


class TestListTools:
    async def test_list_tools_returns_mcp_format(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        from cli.helpers.storage import ensure_app, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("testapp")
        write_tools("testapp", [_make_tool("search")])

        server = _create_server()
        handler = server.request_handlers[mcp_types.ListToolsRequest]
        req = mcp_types.ListToolsRequest(method="tools/list")
        result = await handler(req)

        list_result: mcp_types.ListToolsResult = result.root  # type: ignore[assignment]
        assert any(t.name == "testapp_search" for t in list_result.tools)


class TestCallTool:
    @patch("requests.request")
    async def test_call_tool_success(
        self,
        mock_request: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        from cli.helpers.storage import ensure_app, update_app_meta, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("testapp")
        write_tools("testapp", [_make_tool("search")])
        update_app_meta("testapp", base_url="https://api.example.com")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = '{"results": []}'
        mock_request.return_value = mock_resp

        tool = _make_tool("search")
        result = await _handle_call("testapp", tool, {"q": "hello"})

        assert "200" in result
        assert '{"results": []}' in result
        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args
        assert call_kwargs.kwargs["method"] == "POST"
        assert call_kwargs.kwargs["url"] == "https://api.example.com/api/search"
        assert call_kwargs.kwargs["json"] == {"query": "hello"}

    async def test_call_tool_no_base_url(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        from cli.helpers.storage import ensure_app, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("testapp")
        write_tools("testapp", [_make_tool("search")])

        tool = _make_tool("search")
        result = await _handle_call("testapp", tool, {"q": "hello"})

        assert "error" in result.lower()
        assert "base_url" in result

    @patch("requests.request")
    async def test_call_tool_with_auth(
        self,
        mock_request: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        import time

        from cli.formats.mcp_tool import TokenState
        from cli.helpers.storage import (
            ensure_app,
            update_app_meta,
            write_token,
            write_tools,
        )

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("testapp")
        write_tools("testapp", [_make_tool("search")])
        update_app_meta("testapp", base_url="https://api.example.com")

        # Write a valid token
        write_token("testapp", TokenState(
            headers={"Authorization": "Bearer tok123"},
            obtained_at=time.time(),
            expires_at=time.time() + 3600,
        ))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.text = '{"ok": true}'
        mock_request.return_value = mock_resp

        tool = _make_tool("search", requires_auth=True)
        await _handle_call("testapp", tool, {"q": "test"})

        call_kwargs = mock_request.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tok123"

    @patch("requests.request")
    async def test_call_tool_http_error(
        self,
        mock_request: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        from cli.helpers.storage import ensure_app, update_app_meta, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("testapp")
        write_tools("testapp", [_make_tool("search")])
        update_app_meta("testapp", base_url="https://api.example.com")

        mock_request.side_effect = Exception("Connection refused")

        tool = _make_tool("search")
        result = await _handle_call("testapp", tool, {"q": "test"})

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Connection refused" in parsed["error"]


    async def test_call_tool_requires_auth_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        from cli.helpers.storage import ensure_app, update_app_meta, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("testapp")
        write_tools("testapp", [_make_tool("search", requires_auth=True)])
        update_app_meta("testapp", base_url="https://api.example.com")

        tool = _make_tool("search", requires_auth=True)
        result = await _handle_call("testapp", tool, {"q": "test"})

        parsed = json.loads(result)
        assert "error" in parsed
        assert "spectral auth login" in parsed["error"]

    @patch("requests.request")
    async def test_call_tool_no_auth_skips_auth(
        self,
        mock_request: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        from cli.helpers.storage import ensure_app, update_app_meta, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("testapp")
        write_tools("testapp", [_make_tool("search")])
        update_app_meta("testapp", base_url="https://api.example.com")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.text = '{"public": true}'
        mock_request.return_value = mock_resp

        tool = _make_tool("search", requires_auth=False)
        result = await _handle_call("testapp", tool, {"q": "test"})

        assert "200" in result
        # No Authorization header should be present
        call_kwargs = mock_request.call_args
        headers = call_kwargs.kwargs["headers"]
        assert "Authorization" not in headers


class TestServerCallTool:
    async def test_unknown_tool(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))

        server = _create_server()
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = mcp_types.CallToolRequest(
            method="tools/call",
            params=mcp_types.CallToolRequestParams(
                name="nonexistent_tool",
                arguments={},
            ),
        )
        result = await handler(req)
        call_result: mcp_types.CallToolResult = result.root  # type: ignore[assignment]
        assert call_result.content is not None
        assert any("Unknown tool" in c.text for c in call_result.content if isinstance(c, mcp_types.TextContent))


class TestApplyDefaults:
    def test_injects_missing_defaults(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "power": {"type": "string", "default": "ON"},
                "mode": {"type": "string", "default": "HEAT"},
            },
            "required": [],
        }
        result = _apply_defaults({}, schema)
        assert result == {"power": "ON", "mode": "HEAT"}

    def test_preserves_provided_values(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "power": {"type": "string", "default": "ON"},
            },
            "required": [],
        }
        result = _apply_defaults({"power": "OFF"}, schema)
        assert result == {"power": "OFF"}

    def test_ignores_properties_without_default(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "color": {"type": "string", "default": "blue"},
            },
            "required": ["name"],
        }
        result = _apply_defaults({"name": "test"}, schema)
        assert result == {"name": "test", "color": "blue"}
        assert "name" in result  # provided value kept


class TestCallToolWithDefaults:
    @patch("requests.request")
    async def test_call_tool_applies_defaults(
        self,
        mock_request: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        from cli.helpers.storage import ensure_app, update_app_meta, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("testapp")
        update_app_meta("testapp", base_url="https://api.example.com")

        tool = ToolDefinition(
            name="set_overlay",
            description="Set temperature overlay",
            parameters={
                "type": "object",
                "properties": {
                    "zone_id": {"type": "integer"},
                    "temperature": {"type": "number"},
                    "power": {"type": "string", "default": "ON"},
                    "mode": {"type": "string", "default": "HEAT"},
                },
                "required": ["zone_id", "temperature"],
            },
            request=ToolRequest(
                method="PUT",
                path="/api/zones/{zone_id}/overlay",
                body={
                    "temperature": {"$param": "temperature"},
                    "setting": {
                        "power": {"$param": "power"},
                        "mode": {"$param": "mode"},
                    },
                },
            ),
            requires_auth=False,
        )
        write_tools("testapp", [tool])

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.text = '{"ok": true}'
        mock_request.return_value = mock_resp

        # Register and call via server handler
        server = _create_server()
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = mcp_types.CallToolRequest(
            method="tools/call",
            params=mcp_types.CallToolRequestParams(
                name="testapp_set_overlay",
                arguments={"zone_id": 1, "temperature": 22.5},
            ),
        )
        result = await handler(req)
        call_result: mcp_types.CallToolResult = result.root  # type: ignore[assignment]

        # Should succeed (no "Missing required parameter" error)
        assert any("200" in c.text for c in call_result.content if isinstance(c, mcp_types.TextContent))

        # Verify defaults were applied in the request body
        call_kwargs = mock_request.call_args
        body = call_kwargs.kwargs["json"]
        assert body["setting"]["power"] == "ON"
        assert body["setting"]["mode"] == "HEAT"
