"""Tests for REST mechanical extraction."""
# pyright: reportPrivateUsage=false

import json

from cli.commands.analyze.steps.rest.extraction import (
    _build_endpoint_mechanical,
    _make_endpoint_id,
    extract_rate_limit,
    find_traces_for_group,
)
from cli.commands.analyze.steps.rest.types import EndpointGroup
from cli.formats.capture_bundle import Header
from tests.conftest import make_trace


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
            urls=[
                "https://api.example.com/users/123",
                "https://api.example.com/users/456",
            ],
        )
        matched = find_traces_for_group(group, traces)
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
        matched = find_traces_for_group(group, traces)
        assert len(matched) == 2


class TestBuildEndpointMechanical:
    def test_basic_endpoint(self):
        traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/api/users",
                200,
                timestamp=1000000,
                response_body=json.dumps({"name": "Alice"}).encode(),
                request_headers=[Header(name="Authorization", value="Bearer tok")],
            ),
        ]
        endpoint = _build_endpoint_mechanical("GET", "/api/users", traces)
        assert endpoint.method == "GET"
        assert endpoint.path == "/api/users"

    def test_endpoint_with_path_params(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users/123", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/users/456", 200, 2000),
        ]
        endpoint = _build_endpoint_mechanical("GET", "/users/{user_id}", traces)
        assert endpoint.request.path_schema is not None
        props = endpoint.request.path_schema["properties"]
        assert "user_id" in props
        assert "123" in props["user_id"]["observed"]
        assert "456" in props["user_id"]["observed"]

    def test_endpoint_with_query_params(self):
        traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/items?id=a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                200,
                1000,
            ),
            make_trace(
                "t_0002",
                "GET",
                "https://api.example.com/items?id=11111111-2222-3333-4444-555555555555",
                200,
                2000,
            ),
        ]
        endpoint = _build_endpoint_mechanical("GET", "/items", traces)
        assert endpoint.request.query_schema is not None
        props = endpoint.request.query_schema["properties"]
        assert "id" in props
        assert props["id"]["format"] == "uuid"

    def test_endpoint_with_body_schema(self):
        traces = [
            make_trace(
                "t_0001",
                "POST",
                "https://api.example.com/api/orders",
                201,
                timestamp=1000,
                request_body=json.dumps(
                    {"product_id": "p1", "quantity": 2}
                ).encode(),
                request_headers=[Header(name="Content-Type", value="application/json")],
            ),
        ]
        endpoint = _build_endpoint_mechanical("POST", "/api/orders", traces)
        assert endpoint.request.body_schema is not None
        props = endpoint.request.body_schema["properties"]
        assert "product_id" in props
        assert "quantity" in props
        assert props["product_id"]["type"] == "string"
        assert props["quantity"]["type"] == "integer"


class TestFormatDetectionInExtraction:
    """Test that detect_format is wired into mechanical extraction for params."""

    def test_body_param_date_format(self):
        traces = [
            make_trace(
                "t_0001",
                "POST",
                "https://api.example.com/api/events",
                201,
                timestamp=1000,
                request_body=json.dumps(
                    {"date": "2024-01-15", "name": "Meeting"}
                ).encode(),
                request_headers=[Header(name="Content-Type", value="application/json")],
            ),
            make_trace(
                "t_0002",
                "POST",
                "https://api.example.com/api/events",
                201,
                timestamp=2000,
                request_body=json.dumps(
                    {"date": "2024-02-20", "name": "Conference"}
                ).encode(),
                request_headers=[Header(name="Content-Type", value="application/json")],
            ),
        ]
        endpoint = _build_endpoint_mechanical("POST", "/api/events", traces)
        assert endpoint.request.body_schema is not None
        props = endpoint.request.body_schema["properties"]
        assert props["date"]["format"] == "date"
        assert "format" not in props["name"]  # not a recognizable format

    def test_query_param_uuid_format(self):
        traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/items?id=a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                200,
                timestamp=1000,
            ),
            make_trace(
                "t_0002",
                "GET",
                "https://api.example.com/items?id=11111111-2222-3333-4444-555555555555",
                200,
                timestamp=2000,
            ),
        ]
        endpoint = _build_endpoint_mechanical("GET", "/items", traces)
        assert endpoint.request.query_schema is not None
        assert endpoint.request.query_schema["properties"]["id"]["format"] == "uuid"

    def test_non_string_body_param_no_format(self):
        traces = [
            make_trace(
                "t_0001",
                "POST",
                "https://api.example.com/api/count",
                200,
                timestamp=1000,
                request_body=json.dumps({"count": 42}).encode(),
                request_headers=[Header(name="Content-Type", value="application/json")],
            ),
        ]
        endpoint = _build_endpoint_mechanical("POST", "/api/count", traces)
        assert endpoint.request.body_schema is not None
        assert "format" not in endpoint.request.body_schema["properties"]["count"]


class TestRateLimitExtraction:
    def test_extracts_rate_limit_headers(self):
        traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/data",
                200,
                timestamp=1000,
                response_headers=[
                    Header(name="Content-Type", value="application/json"),
                    Header(name="X-RateLimit-Limit", value="100"),
                    Header(name="X-RateLimit-Remaining", value="95"),
                    Header(name="X-RateLimit-Reset", value="1700000000"),
                ],
            ),
        ]
        result = extract_rate_limit(traces)
        assert result is not None
        assert "limit=100" in result
        assert "remaining=95" in result
        assert "reset=1700000000" in result

    def test_no_rate_limit_headers(self):
        traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/data",
                200,
                timestamp=1000,
                response_headers=[
                    Header(name="Content-Type", value="application/json"),
                ],
            ),
        ]
        result = extract_rate_limit(traces)
        assert result is None

    def test_retry_after_only(self):
        traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/data",
                429,
                timestamp=1000,
                response_headers=[
                    Header(name="Content-Type", value="application/json"),
                    Header(name="Retry-After", value="30"),
                ],
            ),
        ]
        result = extract_rate_limit(traces)
        assert result is not None
        assert "retry-after=30" in result
