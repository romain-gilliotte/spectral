"""Tests for REST enrichment application."""

from typing import Any

from cli.commands.analyze.steps.rest.enrich import (
    _apply_enrichment as _apply_enrichment,  # pyright: ignore[reportPrivateUsage]
    _build_endpoint_summary as _build_endpoint_summary,  # pyright: ignore[reportPrivateUsage]
    _strip_non_leaf_observed as _strip_non_leaf_observed,  # pyright: ignore[reportPrivateUsage]
)
from cli.commands.analyze.steps.rest.types import (
    EndpointSpec,
    RequestSpec,
    ResponseSpec,
)


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


class TestStripNonLeafObserved:
    def test_strips_root_object_observed(self):
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "address": {
                    "type": "object",
                    "observed": [{"city": "Paris"}],
                    "properties": {
                        "city": {"type": "string", "observed": ["Paris"]},
                    },
                },
            },
        }
        result = _strip_non_leaf_observed(schema)
        assert "observed" not in result["properties"]["address"]
        assert result["properties"]["address"]["properties"]["city"]["observed"] == [
            "Paris"
        ]

    def test_strips_deeply_nested_object_observed(self):
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "outer": {
                    "type": "object",
                    "observed": [{"inner": {"val": 1}}],
                    "properties": {
                        "inner": {
                            "type": "object",
                            "observed": [{"val": 1}],
                            "properties": {
                                "val": {"type": "integer", "observed": [1]},
                            },
                        },
                    },
                },
            },
        }
        result = _strip_non_leaf_observed(schema)
        assert "observed" not in result["properties"]["outer"]
        assert "observed" not in result["properties"]["outer"]["properties"]["inner"]
        assert result["properties"]["outer"]["properties"]["inner"]["properties"][
            "val"
        ]["observed"] == [1]

    def test_strips_array_observed(self):
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "observed": [["a", "b"]],
                    "items": {"type": "string", "observed": ["a", "b"]},
                },
            },
        }
        result = _strip_non_leaf_observed(schema)
        assert "observed" not in result["properties"]["tags"]
        assert result["properties"]["tags"]["items"]["observed"] == ["a", "b"]

    def test_keeps_scalar_observed(self):
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "observed": ["Alice"]},
                "age": {"type": "integer", "observed": [30]},
            },
        }
        result = _strip_non_leaf_observed(schema)
        assert result["properties"]["name"]["observed"] == ["Alice"]
        assert result["properties"]["age"]["observed"] == [30]


class TestBuildEndpointSummaryObserved:
    """Verify that _build_endpoint_summary strips intermediate observed from LLM context."""

    def test_body_schema_intermediate_observed_stripped(self):
        ep = EndpointSpec(
            id="test",
            path="/test",
            method="POST",
            request=RequestSpec(
                body_schema={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "object",
                            "observed": [{"city": "Paris"}],
                            "properties": {
                                "city": {"type": "string", "observed": ["Paris"]},
                            },
                        },
                    },
                }
            ),
        )
        summary = _build_endpoint_summary(ep, [], [])
        body = summary["request_body"]
        addr = body["properties"]["address"]
        # Intermediate object observed stripped for LLM
        assert "observed" not in addr
        # Leaf scalar observed kept for LLM
        assert addr["properties"]["city"]["observed"] == ["Paris"]

    def test_response_schema_intermediate_observed_stripped(self):
        ep = EndpointSpec(
            id="test",
            path="/test",
            method="GET",
            responses=[
                ResponseSpec(
                    status=200,
                    schema_={
                        "type": "object",
                        "properties": {
                            "locale": {
                                "type": "object",
                                "observed": [{"fr_FR": "Gilliotte"}],
                                "properties": {
                                    "fr_FR": {
                                        "type": "string",
                                        "observed": ["Gilliotte"],
                                    },
                                },
                            },
                        },
                    },
                ),
            ],
        )
        summary = _build_endpoint_summary(ep, [], [])
        resp_schema = summary["responses"][0]["schema"]
        locale = resp_schema["properties"]["locale"]
        # Intermediate object observed stripped for LLM
        assert "observed" not in locale
        # Leaf scalar observed kept for LLM
        assert locale["properties"]["fr_FR"]["observed"] == ["Gilliotte"]


class TestStripNonLeafObservedAdditionalProperties:
    def test_object_additional_properties_observed_stripped(self):
        schema: dict[str, Any] = {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "observed": [{"total": 100}],
                "properties": {
                    "total": {"type": "integer", "observed": [100]},
                },
            },
            "x-key-pattern": "year",
        }
        result = _strip_non_leaf_observed(schema)
        ap = result["additionalProperties"]
        assert "observed" not in ap
        assert ap["properties"]["total"]["observed"] == [100]

    def test_scalar_additional_properties_untouched(self):
        schema: dict[str, Any] = {
            "type": "object",
            "additionalProperties": {
                "type": "integer",
                "observed": [100, 200],
            },
            "x-key-pattern": "date",
        }
        result = _strip_non_leaf_observed(schema)
        assert result["additionalProperties"]["observed"] == [100, 200]


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
                                        "total": {"type": "integer", "observed": [100]},
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
