"""Tests for the spec builder (mechanical utilities and LLM-first pipeline)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cli.analyze.spec_builder import (
    _build_endpoint_mechanical,
    _build_request_spec,
    _build_response_specs,
    _detect_base_url,
    _detect_format,
    _extract_query_params,
    _find_traces_for_group,
    _get_header,
    _infer_json_schema,
    _make_endpoint_id,
    build_spec,
)
from cli.analyze.llm import EndpointGroup
from cli.formats.capture_bundle import Header
from tests.conftest import make_trace


class TestSchemaInference:
    def test_basic_object_schema(self):
        samples = [
            {"name": "Alice", "age": 30, "active": True},
            {"name": "Bob", "age": 25, "active": False},
        ]
        schema = _infer_json_schema(samples)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["age"]["type"] == "integer"
        assert schema["properties"]["active"]["type"] == "boolean"
        assert set(schema["required"]) == {"name", "age", "active"}

    def test_optional_fields(self):
        samples = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob"},
        ]
        schema = _infer_json_schema(samples)
        assert "name" in schema.get("required", [])
        assert "email" not in schema.get("required", [])

    def test_date_format_detection(self):
        values = ["2024-01-15T10:30:00Z", "2024-02-20T14:00:00Z"]
        assert _detect_format(values) == "date-time"

    def test_date_only_format(self):
        values = ["2024-01-15", "2024-02-20"]
        assert _detect_format(values) == "date"

    def test_email_format(self):
        values = ["alice@example.com", "bob@test.org"]
        assert _detect_format(values) == "email"

    def test_uuid_format(self):
        values = [
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "11111111-2222-3333-4444-555555555555",
        ]
        assert _detect_format(values) == "uuid"

    def test_uri_format(self):
        values = ["https://example.com/page1", "https://example.com/page2"]
        assert _detect_format(values) == "uri"

    def test_no_format(self):
        values = ["hello", "world"]
        assert _detect_format(values) is None


class TestQueryParamExtraction:
    def test_extracts_query_params(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/search?q=hello&page=1", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/search?q=world&page=2", 200, 2000),
        ]
        params = _extract_query_params(traces)
        assert "q" in params
        assert "page" in params
        assert "hello" in params["q"]
        assert "world" in params["q"]


class TestBaseUrlDetection:
    def test_most_common_base_url(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/a", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/b", 200, 2000),
            make_trace("t_0003", "GET", "https://cdn.example.com/img.png", 200, 3000),
        ]
        assert _detect_base_url(traces) == "https://api.example.com"

    def test_empty_traces(self):
        assert _detect_base_url([]) == ""


class TestEndpointId:
    def test_basic(self):
        assert _make_endpoint_id("GET", "/api/users") == "get_api_users"

    def test_with_params(self):
        assert _make_endpoint_id("GET", "/api/users/{id}") == "get_api_users_id"

    def test_root(self):
        assert _make_endpoint_id("GET", "/") == "get"


class TestFindTracesForGroup:
    def test_finds_by_url(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users/123", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/users/456", 200, 2000),
            make_trace("t_0003", "POST", "https://api.example.com/users", 201, 3000),
        ]
        group = EndpointGroup(
            method="GET",
            pattern="/users/{user_id}",
            urls=["https://api.example.com/users/123", "https://api.example.com/users/456"],
        )
        matched = _find_traces_for_group(group, traces)
        assert len(matched) == 2
        assert all(t.meta.request.method == "GET" for t in matched)

    def test_fallback_to_pattern_matching(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users/123", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/users/456", 200, 2000),
        ]
        # Group with only one URL listed, but pattern should match both
        group = EndpointGroup(
            method="GET",
            pattern="/users/{user_id}",
            urls=["https://api.example.com/users/123"],
        )
        matched = _find_traces_for_group(group, traces)
        assert len(matched) == 2


class TestBuildEndpointMechanical:
    def test_basic_endpoint(self):
        traces = [
            make_trace(
                "t_0001", "GET", "https://api.example.com/api/users", 200,
                timestamp=1000000,
                response_body=json.dumps({"name": "Alice"}).encode(),
                request_headers=[Header(name="Authorization", value="Bearer tok")],
            ),
        ]
        endpoint = _build_endpoint_mechanical("GET", "/api/users", traces, [])
        assert endpoint.method == "GET"
        assert endpoint.path == "/api/users"
        assert endpoint.observed_count == 1
        assert endpoint.requires_auth is True
        assert "t_0001" in endpoint.source_trace_refs

    def test_endpoint_with_path_params(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users/123", 200, 1000),
        ]
        endpoint = _build_endpoint_mechanical("GET", "/users/{user_id}", traces, [])
        path_params = [p for p in endpoint.request.parameters if p.location == "path"]
        assert len(path_params) == 1
        assert path_params[0].name == "user_id"


class TestBuildSpec:
    """Tests for the full LLM-first build_spec pipeline with mocked LLM."""

    @pytest.mark.asyncio
    async def test_full_build(self, sample_bundle):
        """Test build_spec with mocked LLM calls."""
        mock_client = AsyncMock()

        # Mock analyze_endpoints response
        endpoint_groups_response = json.dumps([
            {
                "method": "GET",
                "pattern": "/api/users",
                "urls": ["https://api.example.com/api/users"],
            },
            {
                "method": "GET",
                "pattern": "/api/users/{user_id}/orders",
                "urls": [
                    "https://api.example.com/api/users/123/orders",
                    "https://api.example.com/api/users/456/orders",
                ],
            },
            {
                "method": "POST",
                "pattern": "/api/orders",
                "urls": ["https://api.example.com/api/orders"],
            },
        ])

        # Mock auth response
        auth_response = json.dumps({
            "type": "bearer_token",
            "obtain_flow": "login_form",
            "token_header": "Authorization",
            "token_prefix": "Bearer",
            "business_process": "Token-based auth",
            "user_journey": ["Login with credentials", "Receive bearer token"],
        })

        # Mock endpoint detail response
        detail_response = json.dumps({
            "business_purpose": "List users",
            "user_story": "As a user, I want to list users",
            "correlation_confidence": 0.9,
            "parameter_meanings": {},
            "response_meanings": {"200": "Success"},
            "trigger_explanations": [],
        })

        # Mock business context response
        context_response = json.dumps({
            "domain": "User Management",
            "description": "API for managing users and orders",
            "user_personas": ["admin", "user"],
            "key_workflows": [{"name": "browse_users", "description": "Browse user list", "steps": ["login", "view_users"]}],
            "business_glossary": {"user": "A registered account"},
        })

        # Set up mock to return different responses for different calls
        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            msg = kwargs.get("messages", [{}])[0].get("content", "")

            mock_response = MagicMock()
            mock_content = MagicMock()
            mock_content.type = "text"
            mock_response.stop_reason = "end_turn"

            if "Group these observed URLs" in msg:
                mock_content.text = endpoint_groups_response
            elif "authentication mechanism" in msg:
                mock_content.text = auth_response
            elif "business domain" in msg or "Based on these API endpoints" in msg:
                mock_content.text = context_response
            else:
                mock_content.text = detail_response

            mock_response.content = [mock_content]
            return mock_response

        mock_client.messages.create = mock_create

        spec = await build_spec(
            sample_bundle,
            client=mock_client,
            model="test-model",
            source_filename="test.zip",
        )

        assert spec.name == "Test App API"
        assert "test.zip" in spec.source_captures
        assert len(spec.protocols.rest.endpoints) > 0
        assert spec.auth.type == "bearer_token"
        assert spec.business_context.domain == "User Management"
        assert "user" in spec.business_glossary

    @pytest.mark.asyncio
    async def test_websocket_specs_built(self, sample_bundle):
        """WebSocket specs should be built regardless of LLM."""
        mock_client = AsyncMock()

        groups_response = json.dumps([
            {"method": "GET", "pattern": "/api/users", "urls": ["https://api.example.com/api/users"]},
            {"method": "GET", "pattern": "/api/users/{user_id}/orders",
             "urls": ["https://api.example.com/api/users/123/orders", "https://api.example.com/api/users/456/orders"]},
            {"method": "POST", "pattern": "/api/orders", "urls": ["https://api.example.com/api/orders"]},
        ])

        async def mock_create(**kwargs):
            mock_response = MagicMock()
            mock_content = MagicMock()
            mock_content.type = "text"
            mock_response.stop_reason = "end_turn"
            msg = kwargs.get("messages", [{}])[0].get("content", "")
            if "Group these observed URLs" in msg:
                mock_content.text = groups_response
            elif "authentication" in msg:
                mock_content.text = json.dumps({"type": "bearer_token", "token_header": "Authorization", "token_prefix": "Bearer"})
            elif "business domain" in msg or "Based on these API endpoints" in msg:
                mock_content.text = json.dumps({"domain": "", "description": "", "user_personas": [], "key_workflows": [], "business_glossary": {}})
            else:
                mock_content.text = json.dumps({"business_purpose": "test", "user_story": "test", "correlation_confidence": 0.5, "parameter_meanings": {}, "response_meanings": {}, "trigger_explanations": []})
            mock_response.content = [mock_content]
            return mock_response

        mock_client.messages.create = mock_create

        spec = await build_spec(sample_bundle, client=mock_client, model="test-model")

        assert len(spec.protocols.websocket.connections) == 1
        ws = spec.protocols.websocket.connections[0]
        assert ws.url == "wss://realtime.example.com/ws"
        assert ws.subprotocol == "graphql-ws"
        assert len(ws.messages) == 2
