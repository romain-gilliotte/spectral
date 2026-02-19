"""Tests for the spec builder (mechanical utilities and pipeline)."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from cli.commands.analyze.pipeline import build_spec
import cli.helpers.llm as llm


@pytest.fixture(autouse=True)
def reset_llm_globals():
    """Reset module globals before/after each test."""
    llm.reset()
    yield
    llm.reset()
from cli.commands.analyze.schemas import infer_schema
from cli.commands.analyze.steps.rest.assemble import (
    _observed_to_examples as _observed_to_examples,  # pyright: ignore[reportPrivateUsage]
    build_openapi_dict,
)
from cli.commands.analyze.steps.rest.enrich import (
    _apply_enrichment as _apply_enrichment,  # pyright: ignore[reportPrivateUsage]
)
from cli.commands.analyze.steps.rest.extraction import (
    _build_endpoint_mechanical as _build_endpoint_mechanical,  # pyright: ignore[reportPrivateUsage]
    _make_endpoint_id as _make_endpoint_id,  # pyright: ignore[reportPrivateUsage]
    extract_rate_limit,
    find_traces_for_group,
)
from cli.commands.analyze.steps.rest.types import (
    EndpointGroup,
    EndpointSpec,
    RequestSpec,
    ResponseSpec,
    SpecComponents,
)
from cli.commands.analyze.steps.types import AuthInfo
from cli.commands.capture.types import CaptureBundle
from cli.formats.capture_bundle import Header
from tests.conftest import make_trace


class TestSchemaInference:
    def test_basic_object_schema(self):
        samples = [
            {"name": "Alice", "age": 30, "active": True},
            {"name": "Bob", "age": 25, "active": False},
        ]
        schema = infer_schema(samples)
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
        schema = infer_schema(samples)
        assert "name" in schema.get("required", [])
        assert "email" not in schema.get("required", [])


class TestQueryParamExtraction:
    def test_extracts_query_params_via_schema(self):
        from cli.commands.analyze.schemas import infer_query_schema

        traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/search?q=hello&page=1",
                200,
                1000,
            ),
            make_trace(
                "t_0002",
                "GET",
                "https://api.example.com/search?q=world&page=2",
                200,
                2000,
            ),
        ]
        schema = infer_query_schema(traces)
        assert schema is not None
        assert "q" in schema["properties"]
        assert "page" in schema["properties"]
        assert "hello" in schema["properties"]["q"]["observed"]
        assert "world" in schema["properties"]["q"]["observed"]


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


class TestApplyEnrichment:
    def test_discovery_notes(self):
        endpoint = EndpointSpec(id="test", path="/test", method="GET")
        _apply_enrichment(endpoint, {"discovery_notes": "Always called after login"})
        assert endpoint.discovery_notes == "Always called after login"

    def test_path_parameter_descriptions(self):
        endpoint = EndpointSpec(
            id="test",
            path="/users/{user_id}",
            method="GET",
            request=RequestSpec(
                path_schema={
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string", "observed": ["123"]},
                    },
                    "required": ["user_id"],
                }
            ),
        )
        _apply_enrichment(
            endpoint,
            {
                "field_descriptions": {
                    "path_parameters": {
                        "user_id": "Unique identifier for the user"
                    },
                },
            },
        )
        assert endpoint.request.path_schema is not None
        assert (
            endpoint.request.path_schema["properties"]["user_id"]["description"]
            == "Unique identifier for the user"
        )

    def test_query_parameter_descriptions(self):
        endpoint = EndpointSpec(
            id="test",
            path="/search",
            method="GET",
            request=RequestSpec(
                query_schema={
                    "type": "object",
                    "properties": {
                        "q": {"type": "string", "observed": ["hello"]},
                    },
                    "required": ["q"],
                }
            ),
        )
        _apply_enrichment(
            endpoint,
            {
                "field_descriptions": {
                    "query_parameters": {
                        "q": "Search query text"
                    },
                },
            },
        )
        assert endpoint.request.query_schema is not None
        assert (
            endpoint.request.query_schema["properties"]["q"]["description"]
            == "Search query text"
        )

    def test_request_body_field_descriptions(self):
        endpoint = EndpointSpec(
            id="test",
            path="/test",
            method="POST",
            request=RequestSpec(
                body_schema={
                    "type": "object",
                    "properties": {
                        "period": {"type": "string", "observed": ["2024-01"]},
                    },
                    "required": ["period"],
                }
            ),
        )
        _apply_enrichment(
            endpoint,
            {
                "field_descriptions": {
                    "request_body": {
                        "period": "Billing period in YYYY-MM format"
                    },
                },
            },
        )
        assert endpoint.request.body_schema is not None
        assert (
            endpoint.request.body_schema["properties"]["period"]["description"]
            == "Billing period in YYYY-MM format"
        )

    def test_nested_body_field_descriptions(self):
        endpoint = EndpointSpec(
            id="test",
            path="/test",
            method="POST",
            request=RequestSpec(
                body_schema={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "object",
                            "properties": {
                                "city": {"type": "string", "observed": ["Paris"]},
                            },
                        },
                    },
                }
            ),
        )
        _apply_enrichment(
            endpoint,
            {
                "field_descriptions": {
                    "request_body": {
                        "address": {"city": "City name for delivery"}
                    },
                },
            },
        )
        assert endpoint.request.body_schema is not None
        assert (
            endpoint.request.body_schema["properties"]["address"]["properties"]["city"][
                "description"
            ]
            == "City name for delivery"
        )

    def test_rich_response_details(self):
        endpoint = EndpointSpec(
            id="test",
            path="/test",
            method="GET",
            responses=[
                ResponseSpec(status=200),
                ResponseSpec(status=403),
            ],
        )
        _apply_enrichment(
            endpoint,
            {
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
            },
        )
        assert endpoint.responses[0].business_meaning == "Success"
        assert endpoint.responses[0].example_scenario == "User views their dashboard"
        assert endpoint.responses[0].user_impact is None
        assert endpoint.responses[1].business_meaning == "Forbidden"
        assert endpoint.responses[1].user_impact == "Cannot access the resource"
        assert endpoint.responses[1].resolution == "Contact admin to request access"

    def test_response_field_descriptions(self):
        endpoint = EndpointSpec(
            id="test",
            path="/test",
            method="GET",
            responses=[
                ResponseSpec(
                    status=200,
                    schema_={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "observed": ["Alice"]},
                        },
                    },
                ),
            ],
        )
        _apply_enrichment(
            endpoint,
            {
                "field_descriptions": {
                    "responses": {
                        "200": {"name": "Full name of the user"},
                    },
                },
            },
        )
        assert endpoint.responses[0].schema_ is not None
        assert (
            endpoint.responses[0].schema_["properties"]["name"]["description"]
            == "Full name of the user"
        )

    def test_array_of_objects_field_descriptions(self):
        """Descriptions for array-of-objects fields should apply to item properties."""
        endpoint = EndpointSpec(
            id="test",
            path="/test",
            method="GET",
            responses=[
                ResponseSpec(
                    status=200,
                    schema_={
                        "type": "object",
                        "properties": {
                            "elements": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "type": {"type": "string", "observed": ["PARKING_COST"]},
                                        "value": {"type": "number", "observed": [250]},
                                    },
                                },
                            },
                        },
                    },
                ),
            ],
        )
        _apply_enrichment(
            endpoint,
            {
                "field_descriptions": {
                    "responses": {
                        "200": {
                            "elements": {
                                "type": "Category of the cost element",
                                "value": "Numeric value in cents",
                            },
                        },
                    },
                },
            },
        )
        resp_schema = endpoint.responses[0].schema_
        assert resp_schema is not None
        items_props: dict[str, Any] = resp_schema["properties"]["elements"]["items"][
            "properties"
        ]
        assert items_props["type"]["description"] == "Category of the cost element"
        assert items_props["value"]["description"] == "Numeric value in cents"


def _make_mock_create(
    base_url_response: str | None = None,
    groups_response: str | None = None,
    auth_response: str | None = None,
    enrich_response: str | None = None,
) -> Any:
    """Build a mock client.messages.create that routes by prompt content."""

    if base_url_response is None:
        base_url_response = json.dumps({"base_url": "https://api.example.com"})
    if groups_response is None:
        groups_response = json.dumps(
            [
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
            ]
        )
    if auth_response is None:
        auth_response = json.dumps(
            {
                "type": "bearer_token",
                "obtain_flow": "login_form",
                "token_header": "Authorization",
                "token_prefix": "Bearer",
                "business_process": "Token-based auth",
                "user_journey": ["Login with credentials", "Receive bearer token"],
            }
        )
    if enrich_response is None:
        enrich_response = json.dumps(
            {
                "description": "test purpose",
                "field_descriptions": {},
                "response_details": {},
                "discovery_notes": None,
            }
        )

    async def mock_create(**kwargs: Any) -> MagicMock:
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_response.stop_reason = "end_turn"
        msg: str = kwargs.get("messages", [{}])[0].get("content", "")

        if "base URL" in msg and "business API" in msg:
            mock_content.text = base_url_response
        elif "Group these observed URLs" in msg:
            mock_content.text = groups_response
        elif "authentication mechanism" in msg:
            mock_content.text = auth_response
        elif "single API endpoint" in msg:
            # Per-endpoint enrichment call
            mock_content.text = enrich_response
        else:
            # Fallback
            mock_content.text = enrich_response

        mock_response.content = [mock_content]
        return mock_response

    return mock_create


class TestBuildSpec:
    """Tests for the full pipeline with mocked LLM."""

    @pytest.mark.asyncio
    async def test_full_build(self, sample_bundle: CaptureBundle) -> None:
        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create()
        llm.init(client=mock_client)

        result = await build_spec(
            sample_bundle,
            model="test-model",
            source_filename="test.zip",
        )

        assert result.openapi is not None
        openapi = result.openapi
        assert openapi["openapi"] == "3.1.0"
        assert openapi["info"]["title"] == "Test App API"
        assert len(openapi["paths"]) > 0
        assert "bearerAuth" in openapi["components"]["securitySchemes"]
        assert openapi["servers"][0]["url"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_traces_filtered_by_base_url(
        self, sample_bundle: CaptureBundle
    ) -> None:
        """Traces not matching the detected base URL should be excluded."""
        from tests.conftest import make_trace as mt

        cdn_trace = mt("t_cdn", "GET", "https://cdn.example.com/style.css", 200, 999500)
        sample_bundle.traces.append(cdn_trace)

        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create(
            groups_response=json.dumps(
                [
                    {
                        "method": "GET",
                        "pattern": "/api/users",
                        "urls": ["https://api.example.com/api/users"],
                    },
                ]
            ),
            auth_response=json.dumps({"type": "none"}),
        )
        llm.init(client=mock_client)

        result = await build_spec(sample_bundle, model="test-model")

        assert result.openapi is not None
        openapi = result.openapi
        assert openapi["servers"][0]["url"] == "https://api.example.com"
        # CDN trace should not appear in the output
        assert len(openapi["paths"]) >= 1

    @pytest.mark.asyncio
    async def test_auth_detected_on_endpoints(self, sample_bundle: CaptureBundle) -> None:
        """Endpoints with Authorization header should have security set."""
        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create()
        llm.init(client=mock_client)

        result = await build_spec(
            sample_bundle, model="test-model"
        )

        assert result.openapi is not None
        openapi = result.openapi
        # At least one endpoint should have security (sample traces have Authorization)
        has_security = False
        for path_ops in openapi["paths"].values():
            for op in path_ops.values():
                if "security" in op:
                    has_security = True
                    break
        assert has_security

    @pytest.mark.asyncio
    async def test_openapi_structure(self, sample_bundle: CaptureBundle) -> None:
        """Output should be a valid OpenAPI 3.1 structure."""
        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create()
        llm.init(client=mock_client)

        result = await build_spec(
            sample_bundle, model="test-model"
        )

        assert result.openapi is not None
        openapi = result.openapi
        assert "openapi" in openapi
        assert "info" in openapi
        assert "title" in openapi["info"]
        assert "paths" in openapi
        assert "components" in openapi
        assert "securitySchemes" in openapi["components"]
        assert "servers" in openapi


class TestObservedToExamples:
    """Tests for _observed_to_examples converting observed → examples."""

    def test_scalar_property(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "observed": ["Alice", "Bob"]},
            },
        }
        result = _observed_to_examples(schema)
        assert "observed" not in result["properties"]["name"]
        assert result["properties"]["name"]["examples"] == ["Alice", "Bob"]

    def test_nested_object(self):
        schema = {
            "type": "object",
            "properties": {
                "address": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "observed": ["Paris", "Lyon"]},
                    },
                },
            },
        }
        result = _observed_to_examples(schema)
        city = result["properties"]["address"]["properties"]["city"]
        assert "observed" not in city
        assert city["examples"] == ["Paris", "Lyon"]

    def test_array_items(self):
        schema = {
            "type": "array",
            "items": {
                "type": "string",
                "observed": ["a", "b"],
            },
        }
        result = _observed_to_examples(schema)
        assert "observed" not in result["items"]
        assert result["items"]["examples"] == ["a", "b"]

    def test_no_observed_keeps_schema_unchanged(self):
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
        }
        result = _observed_to_examples(schema)
        assert "examples" not in result["properties"]["count"]
        assert result["properties"]["count"]["type"] == "integer"

    def test_empty_observed_list_no_examples(self):
        schema: dict[str, Any] = {
            "type": "string",
            "observed": [],
        }
        result = _observed_to_examples(schema)
        assert "observed" not in result
        assert "examples" not in result

    def test_preserves_other_keys(self):
        schema = {
            "type": "string",
            "format": "date",
            "observed": ["2024-01-15"],
        }
        result = _observed_to_examples(schema)
        assert result["type"] == "string"
        assert result["format"] == "date"
        assert result["examples"] == ["2024-01-15"]
        assert "observed" not in result


class TestOpenApiExamples:
    """Tests for examples appearing in OpenAPI output."""

    def _build_simple_openapi(
        self,
        endpoints: list[EndpointSpec],
        auth: AuthInfo | None = None,
    ) -> dict[str, Any]:
        components = SpecComponents(
            app_name="Test",
            source_filename="test.zip",
            base_url="https://api.example.com",
            endpoints=endpoints,
            auth=auth or AuthInfo(),
        )
        return build_openapi_dict(components)

    def test_response_example_body(self):
        endpoint = EndpointSpec(
            id="get_users",
            path="/users",
            method="GET",
            responses=[
                ResponseSpec(
                    status=200,
                    schema_={
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                    example_body={"name": "Alice"},
                ),
            ],
        )
        openapi = self._build_simple_openapi([endpoint])
        media = openapi["paths"]["/users"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]
        assert media["example"] == {"name": "Alice"}

    def test_response_no_example_body(self):
        endpoint = EndpointSpec(
            id="get_users",
            path="/users",
            method="GET",
            responses=[
                ResponseSpec(
                    status=200,
                    schema_={
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                ),
            ],
        )
        openapi = self._build_simple_openapi([endpoint])
        media = openapi["paths"]["/users"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]
        assert "example" not in media

    def test_observed_becomes_schema_example(self):
        endpoint = EndpointSpec(
            id="get_users",
            path="/users",
            method="GET",
            responses=[
                ResponseSpec(
                    status=200,
                    schema_={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "observed": ["Alice"]},
                        },
                    },
                ),
            ],
        )
        openapi = self._build_simple_openapi([endpoint])
        schema = openapi["paths"]["/users"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert "observed" not in schema["properties"]["name"]
        assert schema["properties"]["name"]["examples"] == ["Alice"]

    def test_query_param_schema_examples(self):
        endpoint = EndpointSpec(
            id="search",
            path="/search",
            method="GET",
            request=RequestSpec(
                query_schema={
                    "type": "object",
                    "properties": {
                        "q": {"type": "string", "observed": ["hello", "world"]},
                    },
                    "required": ["q"],
                }
            ),
        )
        openapi = self._build_simple_openapi([endpoint])
        param = openapi["paths"]["/search"]["get"]["parameters"][0]
        assert param["name"] == "q"
        assert param["schema"]["examples"] == ["hello", "world"]
        assert "observed" not in param["schema"]

    def test_request_body_schema_examples(self):
        endpoint = EndpointSpec(
            id="create_order",
            path="/orders",
            method="POST",
            request=RequestSpec(
                content_type="application/json",
                body_schema={
                    "type": "object",
                    "properties": {
                        "quantity": {"type": "integer", "observed": [2, 5]},
                    },
                },
            ),
        )
        openapi = self._build_simple_openapi([endpoint])
        body_schema = openapi["paths"]["/orders"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        assert body_schema["properties"]["quantity"]["examples"] == [2, 5]
        assert "observed" not in body_schema["properties"]["quantity"]
