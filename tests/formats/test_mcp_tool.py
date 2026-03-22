"""Tests for MCP tool definition, request template, and token state models."""

from cli.formats.app_meta import AppMeta
from cli.formats.mcp_tool import TokenState, ToolDefinition, ToolRequest


class TestToolRequest:
    def test_defaults(self) -> None:
        req = ToolRequest(method="GET", url="https://api.example.com/api/users")
        assert req.headers == {}
        assert req.query == {}
        assert req.body is None
        assert req.content_type == "application/json"

    def test_roundtrip(self) -> None:
        req = ToolRequest(
            method="POST",
            url="https://api.example.com/api/v1/search",
            headers={"X-Client-Version": "3.2.1"},
            query={"format": "json"},
            body={"origin": {"$param": "origin"}, "currency": "EUR"},
            content_type="application/json",
        )
        loaded = ToolRequest.model_validate_json(req.model_dump_json())
        assert loaded.method == "POST"
        assert loaded.headers == {"X-Client-Version": "3.2.1"}
        assert loaded.body == {"origin": {"$param": "origin"}, "currency": "EUR"}


class TestValidateParamRefs:
    def test_unused_parameter_rejected(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Declared parameters not referenced"):
            ToolDefinition(
                name="broken",
                description="Broken tool",
                parameters={
                    "type": "object",
                    "properties": {"category": {"type": "string"}},
                },
                request=ToolRequest(method="GET", url="https://api.example.com/search"),
            )

    def test_all_params_referenced_in_body(self) -> None:
        ToolDefinition(
            name="ok",
            description="OK tool",
            parameters={
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
            request=ToolRequest(method="POST", url="https://api.example.com/search", body={"query": {"$param": "q"}}),
        )

    def test_all_params_referenced_in_url(self) -> None:
        ToolDefinition(
            name="ok",
            description="OK tool",
            parameters={
                "type": "object",
                "properties": {"user_id": {"type": "string"}},
            },
            request=ToolRequest(method="GET", url="https://api.example.com/users/{user_id}"),
        )

    def test_all_params_referenced_in_query(self) -> None:
        ToolDefinition(
            name="ok",
            description="OK tool",
            parameters={
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
            request=ToolRequest(method="GET", url="https://api.example.com/search", query={"q": {"$param": "q"}}),
        )


class TestToolDefinition:
    def test_roundtrip(self) -> None:
        tool = ToolDefinition(
            name="search_routes",
            description="Search for train routes",
            parameters={
                "type": "object",
                "properties": {
                    "origin": {"type": "string"},
                    "destination": {"type": "string"},
                },
                "required": ["origin", "destination"],
            },
            request=ToolRequest(
                method="POST",
                url="https://api.example.com/api/v1/search",
                body={"origin": {"$param": "origin"}, "destination": {"$param": "destination"}},
            ),
        )
        json_str = tool.model_dump_json()
        loaded = ToolDefinition.model_validate_json(json_str)
        assert loaded.name == "search_routes"
        assert loaded.parameters["required"] == ["origin", "destination"]
        assert loaded.request.method == "POST"
        assert loaded.request.body is not None
        assert loaded.request.body["origin"] == {"$param": "origin"}

    def test_minimal(self) -> None:
        tool = ToolDefinition(
            name="get_status",
            description="Get system status",
            parameters={"type": "object", "properties": {}},
            request=ToolRequest(method="GET", url="https://api.example.com/status"),
        )
        assert tool.request.body is None
        assert tool.request.headers == {}

    def test_requires_auth_default_true(self) -> None:
        tool = ToolDefinition(
            name="get_status",
            description="Get system status",
            parameters={"type": "object", "properties": {}},
            request=ToolRequest(method="GET", url="https://api.example.com/status"),
        )
        assert tool.requires_auth is True

    def test_requires_auth_roundtrip(self) -> None:
        tool = ToolDefinition(
            name="get_public_info",
            description="Get public info",
            parameters={"type": "object", "properties": {}},
            request=ToolRequest(method="GET", url="https://api.example.com/public/info"),
            requires_auth=False,
        )
        loaded = ToolDefinition.model_validate_json(tool.model_dump_json())
        assert loaded.requires_auth is False

    def test_backward_compat_missing_requires_auth(self) -> None:
        """Existing tool.json files without requires_auth should default to True."""
        old_json = (
            '{"name":"x","description":"d",'
            '"parameters":{"type":"object","properties":{}},'
            '"request":{"method":"GET","url":"https://api.example.com/x"}}'
        )
        loaded = ToolDefinition.model_validate_json(old_json)
        assert loaded.requires_auth is True


class TestTokenState:
    def test_roundtrip(self) -> None:
        token = TokenState(
            headers={"Authorization": "Bearer ey123"},
            refresh_token="rt_abc",
            expires_at=1700000000.0,
            obtained_at=1699990000.0,
        )
        loaded = TokenState.model_validate_json(token.model_dump_json())
        assert loaded.headers == {"Authorization": "Bearer ey123"}
        assert loaded.refresh_token == "rt_abc"
        assert loaded.expires_at == 1700000000.0
        assert loaded.obtained_at == 1699990000.0

    def test_defaults(self) -> None:
        token = TokenState(
            headers={"Cookie": "session=abc"},
            obtained_at=1699990000.0,
        )
        assert token.refresh_token is None
        assert token.expires_at is None


class TestAppMetaBackwardCompat:
    def test_base_urls_default_empty(self) -> None:
        meta = AppMeta(
            name="test",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        assert meta.base_urls == []

    def test_base_urls_roundtrip(self) -> None:
        meta = AppMeta(
            name="test",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            base_urls=["https://api.example.com"],
        )
        loaded = AppMeta.model_validate_json(meta.model_dump_json())
        assert loaded.base_urls == ["https://api.example.com"]

    def test_old_format_without_base_urls(self) -> None:
        """Existing app.json files without base_urls should still load."""
        old_json = '{"name":"test","created_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:00Z"}'
        meta = AppMeta.model_validate_json(old_json)
        assert meta.base_urls == []
