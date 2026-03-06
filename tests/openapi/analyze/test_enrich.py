"""Tests for REST enrichment application."""
# pyright: reportPrivateUsage=false

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from cli.commands.openapi.analyze.enrich import (
    _apply_enrichment,
    _build_endpoint_summary,
    enrich_endpoints,
)
from cli.commands.openapi.analyze.types import (
    EndpointSpec,
    EnrichmentContext,
    RequestSpec,
    ResponseSpec,
)


class TestEnrichSizeGuard:
    @pytest.mark.asyncio
    async def test_skips_oversized_endpoint(self):
        """Endpoints whose summary exceeds _MAX_SUMMARY_CHARS skip the LLM call."""
        # Build an endpoint with a huge request body schema (many properties).
        # Use request body rather than response schema because response schemas
        # are individually trimmed before the overall size check.
        big_props = {
            f"field_{i}": {
                "type": "string",
                "examples": [f"value_{i}_{'x' * 200}"],
            }
            for i in range(2000)
        }
        ep = EndpointSpec(
            id="big",
            path="/big",
            method="POST",
            request=RequestSpec(
                body_schema={"type": "object", "properties": big_props},
            ),
        )

        ctx = EnrichmentContext(
            endpoints=[ep],
            traces=[],
            correlations=[],
            app_name="test",
            base_url="https://api.example.com",
        )

        mock_ask = AsyncMock(return_value='{"description": "should not be called"}')
        with patch("cli.commands.openapi.analyze.enrich.llm") as mock_llm:
            mock_llm.ask = mock_ask
            result = await enrich_endpoints(ctx)

        mock_ask.assert_not_called()
        assert result[0].description is None

    @pytest.mark.asyncio
    async def test_enriches_normal_endpoint(self):
        """Normal-sized endpoints are enriched as usual."""
        ep = EndpointSpec(
            id="small",
            path="/small",
            method="GET",
            responses=[
                ResponseSpec(
                    status=200,
                    schema_={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "examples": ["Alice"]},
                        },
                    },
                ),
            ],
        )

        ctx = EnrichmentContext(
            endpoints=[ep],
            traces=[],
            correlations=[],
            app_name="test",
            base_url="https://api.example.com",
        )

        mock_ask = AsyncMock(return_value='{"description": "Returns a user"}')
        with patch("cli.commands.openapi.analyze.enrich.llm") as mock_llm:
            mock_llm.ask = mock_ask
            result = await enrich_endpoints(ctx)

        mock_ask.assert_called_once()
        assert result[0].description == "Returns a user"


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
                        "user_id": {"type": "string", "examples": ["123"]},
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
                        "q": {"type": "string", "examples": ["hello"]},
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
                        "period": {"type": "string", "examples": ["2024-01"]},
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
                                "city": {"type": "string", "examples": ["Paris"]},
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
                            "name": {"type": "string", "examples": ["Alice"]},
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
                                        "type": {"type": "string", "examples": ["PARKING_COST"]},
                                        "value": {"type": "number", "examples": [250]},
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


class TestApplyDescriptionsAdditionalProperties:
    def test_descriptions_applied_through_additional_properties(self):
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
                            "balances": {
                                "type": "object",
                                "additionalProperties": {
                                    "type": "object",
                                    "properties": {
                                        "total": {"type": "integer", "examples": [100]},
                                    },
                                },
                                "x-key-pattern": "date",
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
                            "balances": {"total": "Total balance in cents"},
                        },
                    },
                },
            },
        )
        resp_schema = endpoint.responses[0].schema_
        assert resp_schema is not None
        ap = resp_schema["properties"]["balances"]["additionalProperties"]
        assert ap["properties"]["total"]["description"] == "Total balance in cents"


class TestResponseSchemaTrimming:
    def test_large_response_schema_trimmed(self):
        """Response schema above _MAX_RESPONSE_SCHEMA_CHARS is excluded from summary."""
        big_props = {
            f"field_{i}": {
                "type": "string",
                "examples": [f"value_{i}_{'x' * 100}"],
            }
            for i in range(200)
        }
        ep = EndpointSpec(
            id="big",
            path="/big",
            method="POST",
            responses=[
                ResponseSpec(
                    status=200,
                    schema_={"type": "object", "properties": big_props},
                ),
            ],
        )
        summary = _build_endpoint_summary(ep, [], [])
        # Response entry should exist but without a schema key
        assert len(summary["responses"]) == 1
        assert summary["responses"][0]["status"] == 200
        assert "schema" not in summary["responses"][0]

    def test_small_response_schema_kept(self):
        """Response schema below _MAX_RESPONSE_SCHEMA_CHARS stays in summary."""
        ep = EndpointSpec(
            id="small",
            path="/small",
            method="GET",
            responses=[
                ResponseSpec(
                    status=200,
                    schema_={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "examples": ["Alice"]},
                        },
                    },
                ),
            ],
        )
        summary = _build_endpoint_summary(ep, [], [])
        assert len(summary["responses"]) == 1
        assert "schema" in summary["responses"][0]
        assert summary["responses"][0]["schema"]["properties"]["name"]["examples"] == [
            "Alice"
        ]
