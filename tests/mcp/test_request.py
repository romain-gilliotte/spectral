"""Tests for MCP request construction."""
# pyright: reportUnusedVariable=false, reportPrivateUsage=false

from __future__ import annotations

from typing import Any

from cli.commands.mcp.request import (
    _Omit,
    _resolve_body,
    _resolve_query,
    _resolve_url,
    _resolve_value,
    build_request,
)
from cli.formats.mcp_tool import ToolDefinition, ToolRequest


class TestResolveUrl:
    def test_simple_path(self) -> None:
        url = _resolve_url("https://api.example.com", "/api/status", {})
        assert url == "https://api.example.com/api/status"

    def test_path_params(self) -> None:
        url = _resolve_url(
            "https://api.example.com",
            "/api/users/{user_id}/orders/{order_id}",
            {"user_id": "123", "order_id": "456"},
        )
        assert url == "https://api.example.com/api/users/123/orders/456"

    def test_base_url_with_path_prefix(self) -> None:
        url = _resolve_url("https://www.example.com/api/v2", "/users", {})
        assert url == "https://www.example.com/api/v2/users"

    def test_base_url_trailing_slash(self) -> None:
        url = _resolve_url("https://api.example.com/", "/users", {})
        assert url == "https://api.example.com/users"


class TestResolveQuery:
    def test_literal_values(self) -> None:
        result = _resolve_query({"format": "json", "limit": "10"}, {})
        assert result == {"format": "json", "limit": "10"}

    def test_param_markers(self) -> None:
        result = _resolve_query(
            {"q": {"$param": "search_term"}, "limit": "10"},
            {"search_term": "hello"},
        )
        assert result == {"q": "hello", "limit": "10"}


class TestResolveBody:
    def test_none_body(self) -> None:
        assert _resolve_body(None, {}) is None

    def test_fixed_values(self) -> None:
        body = _resolve_body({"currency": "EUR", "version": "1"}, {})
        assert body == {"currency": "EUR", "version": "1"}

    def test_param_markers(self) -> None:
        body = _resolve_body(
            {"origin": {"$param": "origin"}, "currency": "EUR"},
            {"origin": "Paris"},
        )
        assert body == {"origin": "Paris", "currency": "EUR"}

    def test_nested_body(self) -> None:
        body = _resolve_body(
            {"data": {"name": {"$param": "name"}, "fixed": True}},
            {"name": "Alice"},
        )
        assert body == {"data": {"name": "Alice", "fixed": True}}

    def test_array_param(self) -> None:
        passengers = [{"count": 1, "type": "adult"}]
        body = _resolve_body(
            {"passengers": {"$param": "passengers"}, "currency": "EUR"},
            {"passengers": passengers},
        )
        assert body == {"passengers": passengers, "currency": "EUR"}

    def test_array_with_nested_markers(self) -> None:
        body = _resolve_body(
            {"items": [{"name": {"$param": "item_name"}}, {"name": "fixed"}]},
            {"item_name": "dynamic"},
        )
        assert body == {"items": [{"name": "dynamic"}, {"name": "fixed"}]}


class TestBuildRequest:
    def _make_tool(self, **kwargs: Any) -> ToolDefinition:
        defaults: dict[str, Any] = {
            "name": "test_tool",
            "description": "A test tool",
            "parameters": {"type": "object", "properties": {}},
            "request": ToolRequest(method="GET", path="/api/test"),
        }
        defaults.update(kwargs)
        return ToolDefinition(**defaults)

    def test_simple_get(self) -> None:
        tool = self._make_tool()
        method, url, headers, body = build_request(
            tool, "https://api.example.com", {}
        )
        assert method == "GET"
        assert url == "https://api.example.com/api/test"
        assert body is None

    def test_post_with_body(self) -> None:
        tool = self._make_tool(
            request=ToolRequest(
                method="POST",
                path="/api/search",
                body={"q": {"$param": "query"}, "limit": 10},
            )
        )
        method, url, headers, body = build_request(
            tool, "https://api.example.com", {"query": "hello"}
        )
        assert method == "POST"
        assert body == {"q": "hello", "limit": 10}
        assert headers["Content-Type"] == "application/json"

    def test_auth_headers_merged(self) -> None:
        tool = self._make_tool(
            request=ToolRequest(
                method="GET",
                path="/api/data",
                headers={"X-Client": "spectral"},
            )
        )
        method, url, headers, body = build_request(
            tool,
            "https://api.example.com",
            {},
            auth_headers={"Authorization": "Bearer tok123"},
        )
        assert headers["X-Client"] == "spectral"
        assert headers["Authorization"] == "Bearer tok123"

    def test_query_params(self) -> None:
        tool = self._make_tool(
            request=ToolRequest(
                method="GET",
                path="/api/search",
                query={"q": {"$param": "query"}, "limit": "10"},
            )
        )
        method, url, headers, body = build_request(
            tool, "https://api.example.com", {"query": "trains"}
        )
        assert "q=trains" in url
        assert "limit=10" in url

    def test_path_params(self) -> None:
        tool = self._make_tool(
            request=ToolRequest(
                method="GET",
                path="/api/users/{user_id}",
            )
        )
        method, url, headers, body = build_request(
            tool, "https://api.example.com", {"user_id": "42"}
        )
        assert url == "https://api.example.com/api/users/42"

    def test_form_encoded(self) -> None:
        tool = self._make_tool(
            request=ToolRequest(
                method="POST",
                path="/api/login",
                body={"username": {"$param": "user"}, "grant_type": "password"},
                content_type="application/x-www-form-urlencoded",
            )
        )
        method, url, headers, body = build_request(
            tool, "https://api.example.com", {"user": "alice"}
        )
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert "username=alice" in body
        assert "grant_type=password" in body


class TestResolveValueMissingOptional:
    def test_missing_param_returns_omit(self) -> None:
        result = _resolve_value({"$param": "absent"}, {})
        assert result is _Omit.OMIT

    def test_missing_param_omitted_from_dict(self) -> None:
        result = _resolve_value(
            {"keep": "literal", "drop": {"$param": "absent"}},
            {},
        )
        assert result == {"keep": "literal"}

    def test_present_param_still_resolved(self) -> None:
        result = _resolve_value({"$param": "x"}, {"x": 42})
        assert result == 42

    def test_resolve_body_omits_missing_optional(self) -> None:
        body = _resolve_body(
            {"required_field": {"$param": "a"}, "optional_field": {"$param": "b"}},
            {"a": "hello"},
        )
        assert body == {"required_field": "hello"}

    def test_resolve_query_omits_missing_optional(self) -> None:
        result = _resolve_query(
            {"q": {"$param": "search"}, "page": {"$param": "page"}},
            {"search": "hello"},
        )
        assert result == {"q": "hello"}
