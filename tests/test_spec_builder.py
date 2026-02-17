"""Tests for the spec builder (mechanical utilities and pipeline)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from cli.analyze.schemas import detect_format, extract_query_params, infer_json_schema
from cli.analyze.steps import EndpointGroup
from cli.analyze.steps.enrich_and_context import _apply_enrichment
from cli.analyze.steps.mechanical_extraction import (
    _build_endpoint_mechanical,
    _extract_rate_limit,
    _find_traces_for_group,
    _make_endpoint_id,
)
from cli.analyze.pipeline import build_spec
from cli.formats.api_spec import EndpointSpec, ParameterSpec, RequestSpec, ResponseSpec
from cli.formats.capture_bundle import Header
from tests.conftest import make_trace


class TestSchemaInference:
    def test_basic_object_schema(self):
        samples = [
            {"name": "Alice", "age": 30, "active": True},
            {"name": "Bob", "age": 25, "active": False},
        ]
        schema = infer_json_schema(samples)
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
        schema = infer_json_schema(samples)
        assert "name" in schema.get("required", [])
        assert "email" not in schema.get("required", [])

    def test_date_format_detection(self):
        values = ["2024-01-15T10:30:00Z", "2024-02-20T14:00:00Z"]
        assert detect_format(values) == "date-time"

    def test_date_only_format(self):
        values = ["2024-01-15", "2024-02-20"]
        assert detect_format(values) == "date"

    def test_email_format(self):
        values = ["alice@example.com", "bob@test.org"]
        assert detect_format(values) == "email"

    def test_uuid_format(self):
        values = [
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "11111111-2222-3333-4444-555555555555",
        ]
        assert detect_format(values) == "uuid"

    def test_uri_format(self):
        values = ["https://example.com/page1", "https://example.com/page2"]
        assert detect_format(values) == "uri"

    def test_no_format(self):
        values = ["hello", "world"]
        assert detect_format(values) is None


class TestQueryParamExtraction:
    def test_extracts_query_params(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/search?q=hello&page=1", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/search?q=world&page=2", 200, 2000),
        ]
        params = extract_query_params(traces)
        assert "q" in params
        assert "page" in params
        assert "hello" in params["q"]
        assert "world" in params["q"]


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


class TestFormatDetectionInExtraction:
    """Test that detect_format is wired into mechanical extraction for params."""

    def test_body_param_date_format(self):
        traces = [
            make_trace(
                "t_0001", "POST", "https://api.example.com/api/events", 201,
                timestamp=1000,
                request_body=json.dumps({"date": "2024-01-15", "name": "Meeting"}).encode(),
                request_headers=[Header(name="Content-Type", value="application/json")],
            ),
            make_trace(
                "t_0002", "POST", "https://api.example.com/api/events", 201,
                timestamp=2000,
                request_body=json.dumps({"date": "2024-02-20", "name": "Conference"}).encode(),
                request_headers=[Header(name="Content-Type", value="application/json")],
            ),
        ]
        endpoint = _build_endpoint_mechanical("POST", "/api/events", traces, [])
        body_params = {p.name: p for p in endpoint.request.parameters if p.location == "body"}
        assert body_params["date"].format == "date"
        assert body_params["name"].format is None  # not a recognizable format

    def test_query_param_uuid_format(self):
        traces = [
            make_trace(
                "t_0001", "GET",
                "https://api.example.com/items?id=a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                200, timestamp=1000,
            ),
            make_trace(
                "t_0002", "GET",
                "https://api.example.com/items?id=11111111-2222-3333-4444-555555555555",
                200, timestamp=2000,
            ),
        ]
        endpoint = _build_endpoint_mechanical("GET", "/items", traces, [])
        query_params = {p.name: p for p in endpoint.request.parameters if p.location == "query"}
        assert query_params["id"].format == "uuid"

    def test_non_string_body_param_no_format(self):
        traces = [
            make_trace(
                "t_0001", "POST", "https://api.example.com/api/count", 200,
                timestamp=1000,
                request_body=json.dumps({"count": 42}).encode(),
                request_headers=[Header(name="Content-Type", value="application/json")],
            ),
        ]
        endpoint = _build_endpoint_mechanical("POST", "/api/count", traces, [])
        body_params = {p.name: p for p in endpoint.request.parameters if p.location == "body"}
        assert body_params["count"].format is None


class TestRateLimitExtraction:
    def test_extracts_rate_limit_headers(self):
        traces = [
            make_trace(
                "t_0001", "GET", "https://api.example.com/data", 200,
                timestamp=1000,
                response_headers=[
                    Header(name="Content-Type", value="application/json"),
                    Header(name="X-RateLimit-Limit", value="100"),
                    Header(name="X-RateLimit-Remaining", value="95"),
                    Header(name="X-RateLimit-Reset", value="1700000000"),
                ],
            ),
        ]
        result = _extract_rate_limit(traces)
        assert result is not None
        assert "limit=100" in result
        assert "remaining=95" in result
        assert "reset=1700000000" in result

    def test_no_rate_limit_headers(self):
        traces = [
            make_trace(
                "t_0001", "GET", "https://api.example.com/data", 200,
                timestamp=1000,
                response_headers=[
                    Header(name="Content-Type", value="application/json"),
                ],
            ),
        ]
        result = _extract_rate_limit(traces)
        assert result is None

    def test_retry_after_only(self):
        traces = [
            make_trace(
                "t_0001", "GET", "https://api.example.com/data", 429,
                timestamp=1000,
                response_headers=[
                    Header(name="Content-Type", value="application/json"),
                    Header(name="Retry-After", value="30"),
                ],
            ),
        ]
        result = _extract_rate_limit(traces)
        assert result is not None
        assert "retry-after=30" in result

    def test_rate_limit_wired_to_endpoint(self):
        traces = [
            make_trace(
                "t_0001", "GET", "https://api.example.com/data", 200,
                timestamp=1000,
                response_headers=[
                    Header(name="Content-Type", value="application/json"),
                    Header(name="X-RateLimit-Limit", value="1000"),
                ],
            ),
        ]
        endpoint = _build_endpoint_mechanical("GET", "/data", traces, [])
        assert endpoint.rate_limit is not None
        assert "limit=1000" in endpoint.rate_limit


class TestApplyEnrichment:
    def test_discovery_notes(self):
        endpoint = EndpointSpec(id="test", path="/test", method="GET")
        _apply_enrichment(endpoint, {"discovery_notes": "Always called after login"})
        assert endpoint.discovery_notes == "Always called after login"

    def test_parameter_constraints(self):
        endpoint = EndpointSpec(
            id="test", path="/test", method="POST",
            request=RequestSpec(parameters=[
                ParameterSpec(name="period", location="body", type="string"),
            ]),
        )
        _apply_enrichment(endpoint, {
            "parameter_constraints": {"period": "YYYY-MM format, max 24 months history"},
        })
        assert endpoint.request.parameters[0].constraints == "YYYY-MM format, max 24 months history"

    def test_rich_response_details(self):
        endpoint = EndpointSpec(
            id="test", path="/test", method="GET",
            responses=[
                ResponseSpec(status=200),
                ResponseSpec(status=403),
            ],
        )
        _apply_enrichment(endpoint, {
            "response_details": {
                "200": {
                    "business_meaning": "Success",
                    "example_scenario": "User views their dashboard",
                },
                "403": {
                    "business_meaning": "Forbidden",
                    "user_impact": "Cannot access the resource",
                    "resolution": "Contact admin to request access",
                },
            },
        })
        assert endpoint.responses[0].business_meaning == "Success"
        assert endpoint.responses[0].example_scenario == "User views their dashboard"
        assert endpoint.responses[0].user_impact is None
        assert endpoint.responses[1].business_meaning == "Forbidden"
        assert endpoint.responses[1].user_impact == "Cannot access the resource"
        assert endpoint.responses[1].resolution == "Contact admin to request access"

    def test_flat_response_meanings_fallback(self):
        endpoint = EndpointSpec(
            id="test", path="/test", method="GET",
            responses=[ResponseSpec(status=200)],
        )
        _apply_enrichment(endpoint, {
            "response_meanings": {"200": "Successfully retrieved data"},
        })
        assert endpoint.responses[0].business_meaning == "Successfully retrieved data"

    def test_response_details_takes_precedence_over_meanings(self):
        endpoint = EndpointSpec(
            id="test", path="/test", method="GET",
            responses=[ResponseSpec(status=200)],
        )
        _apply_enrichment(endpoint, {
            "response_details": {"200": {"business_meaning": "From details"}},
            "response_meanings": {"200": "From meanings"},
        })
        assert endpoint.responses[0].business_meaning == "From details"


def _make_mock_create(
    base_url_response=None,
    groups_response=None,
    auth_response=None,
    enrich_response=None,
    detail_response=None,
    context_response=None,
):
    """Build a mock client.messages.create that routes by prompt content."""

    if base_url_response is None:
        base_url_response = json.dumps({"base_url": "https://api.example.com"})
    if groups_response is None:
        groups_response = json.dumps([
            {"method": "GET", "pattern": "/api/users", "urls": ["https://api.example.com/api/users"]},
            {"method": "GET", "pattern": "/api/users/{user_id}/orders",
             "urls": ["https://api.example.com/api/users/123/orders", "https://api.example.com/api/users/456/orders"]},
            {"method": "POST", "pattern": "/api/orders", "urls": ["https://api.example.com/api/orders"]},
        ])
    if auth_response is None:
        auth_response = json.dumps({
            "type": "bearer_token", "obtain_flow": "login_form",
            "token_header": "Authorization", "token_prefix": "Bearer",
            "business_process": "Token-based auth",
            "user_journey": ["Login with credentials", "Receive bearer token"],
        })
    if enrich_response is None:
        enrich_response = json.dumps({
            "endpoints": {},
            "business_context": {
                "domain": "User Management",
                "description": "API for managing users and orders",
                "user_personas": ["admin", "user"],
                "key_workflows": [{"name": "browse_users", "description": "Browse user list", "steps": ["login", "view_users"]}],
                "business_glossary": {"user": "A registered account"},
            },
        })
    # detail_response and context_response kept for backward compat but not used in new pipeline

    async def mock_create(**kwargs):
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_response.stop_reason = "end_turn"
        msg = kwargs.get("messages", [{}])[0].get("content", "")

        if "base URL" in msg and "business API" in msg:
            mock_content.text = base_url_response
        elif "Group these observed URLs" in msg:
            mock_content.text = groups_response
        elif "authentication mechanism" in msg:
            mock_content.text = auth_response
        elif "SINGLE JSON response" in msg:
            mock_content.text = enrich_response
        elif "business domain" in msg or "Based on these API endpoints" in msg:
            # Fallback for old-style context call (shouldn't happen in new pipeline)
            mock_content.text = context_response or json.dumps({
                "domain": "", "description": "", "user_personas": [],
                "key_workflows": [], "business_glossary": {},
            })
        else:
            # Fallback for old-style detail call
            mock_content.text = detail_response or json.dumps({
                "business_purpose": "test", "user_story": "test",
                "correlation_confidence": 0.5, "parameter_meanings": {},
                "response_meanings": {}, "trigger_explanations": [],
            })

        mock_response.content = [mock_content]
        return mock_response

    return mock_create


class TestBuildSpec:
    """Tests for the full pipeline with mocked LLM."""

    @pytest.mark.asyncio
    async def test_full_build(self, sample_bundle):
        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create()

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
        assert spec.protocols.rest.base_url == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_websocket_specs_built(self, sample_bundle):
        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create()

        spec = await build_spec(sample_bundle, client=mock_client, model="test-model")

        assert len(spec.protocols.websocket.connections) == 1
        ws = spec.protocols.websocket.connections[0]
        assert ws.url == "wss://realtime.example.com/ws"
        assert ws.subprotocol == "graphql-ws"
        assert len(ws.messages) == 2

    @pytest.mark.asyncio
    async def test_traces_filtered_by_base_url(self, sample_bundle):
        """Traces not matching the detected base URL should be excluded."""
        from tests.conftest import make_trace as mt
        cdn_trace = mt("t_cdn", "GET", "https://cdn.example.com/style.css", 200, 999500)
        sample_bundle.traces.append(cdn_trace)

        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create(
            groups_response=json.dumps([
                {"method": "GET", "pattern": "/api/users", "urls": ["https://api.example.com/api/users"]},
            ]),
            auth_response=json.dumps({"type": "none"}),
        )

        spec = await build_spec(sample_bundle, client=mock_client, model="test-model")

        all_refs = []
        for ep in spec.protocols.rest.endpoints:
            all_refs.extend(ep.source_trace_refs)
        assert "t_cdn" not in all_refs
        assert spec.protocols.rest.base_url == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_api_name_from_enrichment(self, sample_bundle):
        """When the LLM returns an api_name, it should be used as spec.name."""
        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create(
            enrich_response=json.dumps({
                "endpoints": {},
                "business_context": {
                    "api_name": "Acme User Management API",
                    "domain": "User Management",
                    "description": "API for managing users",
                    "user_personas": [],
                    "key_workflows": [],
                    "business_glossary": {},
                },
            }),
        )
        spec = await build_spec(sample_bundle, client=mock_client, model="test-model")
        assert spec.name == "Acme User Management API"

    @pytest.mark.asyncio
    async def test_api_name_fallback_to_app_name(self, sample_bundle):
        """When no api_name is returned, fall back to bundle app name."""
        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create(
            enrich_response=json.dumps({
                "endpoints": {},
                "business_context": {
                    "domain": "User Management",
                    "description": "API for managing users",
                    "user_personas": [],
                    "key_workflows": [],
                    "business_glossary": {},
                },
            }),
        )
        spec = await build_spec(sample_bundle, client=mock_client, model="test-model")
        assert spec.name == "Test App API"

    @pytest.mark.asyncio
    async def test_ws_enrichment_applied(self, sample_bundle):
        """When the LLM returns websocket_purposes, they should be applied."""
        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create(
            enrich_response=json.dumps({
                "endpoints": {},
                "business_context": {
                    "domain": "Test",
                    "description": "Test API",
                    "user_personas": [],
                    "key_workflows": [],
                    "business_glossary": {},
                },
                "websocket_purposes": {
                    "ws_0001": "Real-time data streaming for live updates",
                },
            }),
        )
        spec = await build_spec(sample_bundle, client=mock_client, model="test-model")
        ws = spec.protocols.websocket.connections[0]
        assert ws.business_purpose == "Real-time data streaming for live updates"
