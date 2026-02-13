"""Tests for the spec builder (mechanical analysis)."""

import json

from cli.analyze.spec_builder import (
    _detect_auth,
    _detect_base_url,
    _detect_format,
    _extract_query_params,
    _group_by_endpoint,
    _infer_json_schema,
    _infer_path_patterns,
    _looks_like_id,
    _make_endpoint_id,
    build_spec,
)
from cli.formats.capture_bundle import Header
from tests.conftest import make_trace


class TestPathParameterInference:
    def test_numeric_ids(self):
        paths = ["/users/123/orders", "/users/456/orders"]
        result = _infer_path_patterns(paths)
        assert result["/users/123/orders"] == "/users/{user_id}/orders"
        assert result["/users/456/orders"] == "/users/{user_id}/orders"

    def test_uuid_ids(self):
        paths = [
            "/items/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "/items/11111111-2222-3333-4444-555555555555",
        ]
        result = _infer_path_patterns(paths)
        assert "{item_id}" in result[paths[0]]

    def test_no_parameterization_for_static_paths(self):
        paths = ["/api/users", "/api/users"]
        result = _infer_path_patterns(paths)
        assert result["/api/users"] == "/api/users"

    def test_single_path_not_parameterized(self):
        paths = ["/api/users/123"]
        result = _infer_path_patterns(paths)
        assert result["/api/users/123"] == "/api/users/123"

    def test_mixed_static_and_dynamic(self):
        paths = ["/api/v1/users/123", "/api/v1/users/456"]
        result = _infer_path_patterns(paths)
        assert result["/api/v1/users/123"] == "/api/v1/users/{user_id}"

    def test_alpha_segments_not_parameterized(self):
        """Non-ID-like segments (e.g., words) should not be parameterized."""
        paths = ["/api/users/list", "/api/users/search"]
        result = _infer_path_patterns(paths)
        # "list" and "search" don't look like IDs
        assert result["/api/users/list"] == "/api/users/list"


class TestLooksLikeId:
    def test_numeric(self):
        assert _looks_like_id("123") is True
        assert _looks_like_id("0") is True

    def test_uuid(self):
        assert _looks_like_id("a1b2c3d4-e5f6-7890-abcd-ef1234567890") is True

    def test_hex_hash(self):
        assert _looks_like_id("deadbeef12345678") is True

    def test_word_not_id(self):
        assert _looks_like_id("users") is False
        assert _looks_like_id("list") is False

    def test_short_hex_not_id(self):
        assert _looks_like_id("abc") is False


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


class TestEndpointGrouping:
    def test_groups_by_method_and_path(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/users", 200, 2000),
            make_trace("t_0003", "POST", "https://api.example.com/users", 201, 3000),
        ]
        groups = _group_by_endpoint(traces)
        assert ("GET", "/users") in groups
        assert ("POST", "/users") in groups
        assert len(groups[("GET", "/users")]) == 2
        assert len(groups[("POST", "/users")]) == 1

    def test_parameterizes_varying_segments(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users/123", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/users/456", 200, 2000),
        ]
        groups = _group_by_endpoint(traces)
        keys = list(groups.keys())
        assert len(keys) == 1
        assert "{user_id}" in keys[0][1]


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


class TestAuthDetection:
    def test_bearer_token(self):
        traces = [
            make_trace(
                "t_0001", "GET", "http://localhost/a", 200, 1000,
                request_headers=[Header(name="Authorization", value="Bearer token123")],
            ),
        ]
        auth = _detect_auth(traces)
        assert auth.type == "bearer_token"
        assert auth.token_header == "Authorization"
        assert auth.token_prefix == "Bearer"

    def test_basic_auth(self):
        traces = [
            make_trace(
                "t_0001", "GET", "http://localhost/a", 200, 1000,
                request_headers=[Header(name="Authorization", value="Basic dXNlcjpwYXNz")],
            ),
        ]
        auth = _detect_auth(traces)
        assert auth.type == "basic"
        assert auth.token_prefix == "Basic"

    def test_cookie_auth(self):
        traces = [
            make_trace(
                "t_0001", "GET", "http://localhost/a", 200, 1000,
                request_headers=[Header(name="Cookie", value="session_id=abc123")],
            ),
        ]
        auth = _detect_auth(traces)
        assert auth.type == "cookie"

    def test_no_auth(self):
        traces = [
            make_trace("t_0001", "GET", "http://localhost/a", 200, 1000),
        ]
        auth = _detect_auth(traces)
        assert auth.type == ""


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


class TestBuildSpec:
    def test_full_build(self, sample_bundle):
        spec = build_spec(sample_bundle, source_filename="test.zip")

        assert spec.name == "Test App API"
        assert "test.zip" in spec.source_captures
        assert spec.protocols.rest.base_url == "https://api.example.com"
        assert len(spec.protocols.rest.endpoints) > 0
        assert spec.auth.type == "bearer_token"

    def test_endpoints_have_traces(self, sample_bundle):
        spec = build_spec(sample_bundle)

        for ep in spec.protocols.rest.endpoints:
            assert ep.observed_count > 0
            assert len(ep.source_trace_refs) > 0

    def test_websocket_specs_built(self, sample_bundle):
        spec = build_spec(sample_bundle)

        assert len(spec.protocols.websocket.connections) == 1
        ws = spec.protocols.websocket.connections[0]
        assert ws.url == "wss://realtime.example.com/ws"
        assert ws.subprotocol == "graphql-ws"
        assert len(ws.messages) == 2

    def test_post_endpoint_has_body_params(self, sample_bundle):
        spec = build_spec(sample_bundle)

        post_endpoints = [
            ep for ep in spec.protocols.rest.endpoints if ep.method == "POST"
        ]
        assert len(post_endpoints) >= 1
        ep = post_endpoints[0]
        body_params = [p for p in ep.request.parameters if p.location == "body"]
        assert len(body_params) > 0

    def test_path_parameters_detected(self, sample_bundle):
        spec = build_spec(sample_bundle)

        # Should have an endpoint with path params for /api/users/{user_id}/orders
        endpoints_with_params = [
            ep for ep in spec.protocols.rest.endpoints
            if any(p.location == "path" for p in ep.request.parameters)
        ]
        assert len(endpoints_with_params) >= 1

    def test_response_schemas_inferred(self, sample_bundle):
        spec = build_spec(sample_bundle)

        for ep in spec.protocols.rest.endpoints:
            for resp in ep.responses:
                if resp.status == 200 or resp.status == 201:
                    # Should have either schema or example_body for JSON responses
                    assert resp.schema_ is not None or resp.example_body is not None

    def test_ui_triggers_attached(self, sample_bundle):
        """Endpoints correlated with UI contexts should have triggers."""
        spec = build_spec(sample_bundle)

        all_triggers = []
        for ep in spec.protocols.rest.endpoints:
            all_triggers.extend(ep.ui_triggers)

        # At least some triggers should exist (contexts exist in sample_bundle)
        assert len(all_triggers) > 0
