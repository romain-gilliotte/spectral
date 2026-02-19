"""Tests for REST OpenAPI assembly."""

from typing import Any

from cli.commands.analyze.steps.rest.assemble import (
    _observed_to_examples as _observed_to_examples,  # pyright: ignore[reportPrivateUsage]
    build_openapi_dict,
)
from cli.commands.analyze.steps.rest.types import (
    EndpointSpec,
    RequestSpec,
    ResponseSpec,
    SpecComponents,
)
from cli.commands.analyze.steps.types import AuthInfo


class TestObservedToExamples:
    """Tests for _observed_to_examples converting observed -> examples."""

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
