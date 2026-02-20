"""Tests for schema inference utilities."""

from typing import Any

from cli.commands.analyze.schemas import (
    _detect_format as _detect_format,  # pyright: ignore[reportPrivateUsage]
    _infer_type as _infer_type,  # pyright: ignore[reportPrivateUsage]
    _infer_type_from_values as _infer_type_from_values,  # pyright: ignore[reportPrivateUsage]
    infer_path_schema,
    infer_query_schema,
    infer_schema,
)
from tests.conftest import make_trace


class TestInferSchema:
    def test_basic_properties(self):
        samples = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        schema = infer_schema(samples)
        assert schema["type"] == "object"
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["age"]["type"] == "integer"
        assert "required" not in schema

    def test_observed_values(self):
        samples = [
            {"status": "active", "count": 1},
            {"status": "inactive", "count": 5},
            {"status": "active", "count": 10},
        ]
        schema = infer_schema(samples)
        assert "observed" in schema["properties"]["status"]
        assert "active" in schema["properties"]["status"]["observed"]
        assert "inactive" in schema["properties"]["status"]["observed"]
        assert 1 in schema["properties"]["count"]["observed"]

    def test_observed_values_deduplication(self):
        samples = [
            {"x": "a"},
            {"x": "a"},
            {"x": "b"},
        ]
        schema = infer_schema(samples)
        assert schema["properties"]["x"]["observed"] == ["a", "b"]

    def test_observed_values_max_5(self):
        samples = [{"x": i} for i in range(20)]
        schema = infer_schema(samples)
        assert len(schema["properties"]["x"]["observed"]) == 5

    def test_optional_fields(self):
        samples = [
            {"name": "Alice", "email": "a@b.com"},
            {"name": "Bob"},
        ]
        schema = infer_schema(samples)
        assert "required" not in schema
        assert "name" in schema["properties"]
        assert "email" in schema["properties"]

    def test_format_detection(self):
        samples = [
            {"created_at": "2024-01-15T10:30:00Z"},
            {"created_at": "2024-02-20T14:00:00Z"},
        ]
        schema = infer_schema(samples)
        assert schema["properties"]["created_at"]["format"] == "date-time"

    def test_empty_samples(self):
        schema = infer_schema([])
        assert schema["type"] == "object"
        assert schema["properties"] == {}

    def test_nested_object(self):
        samples = [
            {"address": {"city": "Paris", "zip": "75001"}},
            {"address": {"city": "Lyon", "zip": "69001"}},
        ]
        schema = infer_schema(samples)
        addr = schema["properties"]["address"]
        assert addr["type"] == "object"
        assert "properties" in addr
        assert addr["properties"]["city"]["type"] == "string"
        assert addr["properties"]["zip"]["type"] == "string"
        assert "required" not in addr
        assert "Paris" in addr["properties"]["city"]["observed"]

    def test_array_of_objects(self):
        samples = [
            {"items": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]},
            {"items": [{"id": 3, "name": "C"}]},
        ]
        schema = infer_schema(samples)
        items_prop = schema["properties"]["items"]
        assert items_prop["type"] == "array"
        assert "items" in items_prop
        assert items_prop["items"]["type"] == "object"
        assert "id" in items_prop["items"]["properties"]
        assert items_prop["items"]["properties"]["id"]["type"] == "integer"

    def test_array_of_scalars(self):
        samples = [
            {"tags": ["a", "b"]},
            {"tags": ["c"]},
        ]
        schema = infer_schema(samples)
        tags = schema["properties"]["tags"]
        assert tags["type"] == "array"
        assert tags["items"]["type"] == "string"

    def test_array_observed_on_items_not_property(self):
        """Observed values for arrays should be on items (flattened), not on the array property."""
        samples: list[dict[str, Any]] = [
            {"tags": ["EXT_BUCKET", "EXT_TIME"]},
            {"tags": []},
            {"tags": ["EXT_BUCKET"]},
        ]
        schema = infer_schema(samples)
        tags = schema["properties"]["tags"]
        assert tags["type"] == "array"
        # No observed on the array property itself
        assert "observed" not in tags
        # Observed is on items, with flattened distinct elements
        assert "observed" in tags["items"]
        assert set(tags["items"]["observed"]) == {"EXT_BUCKET", "EXT_TIME"}

    def test_deeply_nested(self):
        samples = [
            {"outer": {"inner": {"value": 42}}},
        ]
        schema = infer_schema(samples)
        inner = schema["properties"]["outer"]["properties"]["inner"]
        assert inner["type"] == "object"
        assert inner["properties"]["value"]["type"] == "integer"
        assert 42 in inner["properties"]["value"]["observed"]

    def test_null_then_object_infers_object_type(self):
        samples = [
            {"point": None},
            {"point": {"lon": 4.82, "lat": 45.73}},
        ]
        schema = infer_schema(samples)
        prop = schema["properties"]["point"]
        assert prop["type"] == "object"
        assert "properties" in prop
        assert prop["properties"]["lon"]["type"] == "number"
        assert prop["properties"]["lat"]["type"] == "number"

    def test_null_then_string_infers_string_type(self):
        samples = [
            {"label": None},
            {"label": "hello"},
        ]
        schema = infer_schema(samples)
        assert schema["properties"]["label"]["type"] == "string"

    def test_all_null_infers_string(self):
        samples = [{"x": None}, {"x": None}]
        schema = infer_schema(samples)
        assert schema["properties"]["x"]["type"] == "string"


class TestInferType:
    def test_bool_before_int(self):
        assert _infer_type(True) == "boolean"

    def test_int(self):
        assert _infer_type(42) == "integer"

    def test_float(self):
        assert _infer_type(3.14) == "number"

    def test_string(self):
        assert _infer_type("hello") == "string"

    def test_list(self):
        assert _infer_type([1, 2]) == "array"

    def test_dict(self):
        assert _infer_type({"a": 1}) == "object"

    def test_none(self):
        assert _infer_type(None) == "string"


class TestInferTypeFromValues:
    def test_integers(self):
        assert _infer_type_from_values(["1", "2", "3"]) == "integer"

    def test_numbers(self):
        assert _infer_type_from_values(["1.5", "2.3"]) == "number"

    def test_booleans(self):
        assert _infer_type_from_values(["true", "false"]) == "boolean"

    def test_strings(self):
        assert _infer_type_from_values(["hello", "world"]) == "string"


class TestDetectFormat:
    def test_date_time(self):
        assert (
            _detect_format(["2024-01-15T10:30:00Z", "2024-02-20T14:00:00Z"])
            == "date-time"
        )

    def test_date_only(self):
        assert _detect_format(["2024-01-15", "2024-02-20"]) == "date"

    def test_email(self):
        assert _detect_format(["alice@example.com", "bob@test.org"]) == "email"

    def test_uuid(self):
        assert (
            _detect_format(
                [
                    "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "11111111-2222-3333-4444-555555555555",
                ]
            )
            == "uuid"
        )

    def test_uri(self):
        assert (
            _detect_format(["https://example.com/page1", "https://example.com/page2"])
            == "uri"
        )

    def test_no_format(self):
        assert _detect_format(["hello", "world"]) is None

    def test_non_string_values(self):
        assert _detect_format([42, 100]) is None


class TestInferPathSchema:
    def test_no_params_returns_none(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users", 200, 1000),
        ]
        assert infer_path_schema(traces, "/users") is None

    def test_single_param(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users/123", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/users/456", 200, 2000),
        ]
        schema = infer_path_schema(traces, "/users/{user_id}")
        assert schema is not None
        assert schema["type"] == "object"
        assert "user_id" in schema["properties"]
        assert schema["required"] == ["user_id"]
        assert "123" in schema["properties"]["user_id"]["observed"]
        assert "456" in schema["properties"]["user_id"]["observed"]

    def test_uuid_format_detection(self):
        traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/items/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                200,
                1000,
            ),
            make_trace(
                "t_0002",
                "GET",
                "https://api.example.com/items/11111111-2222-3333-4444-555555555555",
                200,
                2000,
            ),
        ]
        schema = infer_path_schema(traces, "/items/{item_id}")
        assert schema is not None
        assert schema["properties"]["item_id"]["format"] == "uuid"

    def test_multiple_params(self):
        traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/users/123/orders/o1",
                200,
                1000,
            ),
        ]
        schema = infer_path_schema(traces, "/users/{user_id}/orders/{order_id}")
        assert schema is not None
        assert set(schema["properties"].keys()) == {"user_id", "order_id"}
        assert set(schema["required"]) == {"user_id", "order_id"}

    def test_integer_param(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users/123", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/users/456", 200, 2000),
        ]
        schema = infer_path_schema(traces, "/users/{user_id}")
        assert schema is not None
        assert schema["properties"]["user_id"]["type"] == "integer"


class TestInferQuerySchema:
    def test_no_query_params_returns_none(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users", 200, 1000),
        ]
        assert infer_query_schema(traces) is None

    def test_basic_query_params(self):
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
        schema = infer_query_schema(traces)
        assert schema is not None
        assert schema["type"] == "object"
        assert "id" in schema["properties"]
        assert schema["properties"]["id"]["type"] == "string"
        assert schema["properties"]["id"]["format"] == "uuid"
        assert "required" not in schema
        assert len(schema["properties"]["id"]["observed"]) == 2

    def test_integer_type(self):
        traces = [
            make_trace(
                "t_0001", "GET", "https://api.example.com/search?page=1", 200, 1000
            ),
            make_trace(
                "t_0002", "GET", "https://api.example.com/search?page=2", 200, 2000
            ),
        ]
        schema = infer_query_schema(traces)
        assert schema is not None
        assert schema["properties"]["page"]["type"] == "integer"

    def test_optional_param(self):
        traces = [
            make_trace(
                "t_0001",
                "GET",
                "https://api.example.com/search?q=hello&page=1",
                200,
                1000,
            ),
            make_trace(
                "t_0002", "GET", "https://api.example.com/search?q=world", 200, 2000
            ),
        ]
        schema = infer_query_schema(traces)
        assert schema is not None
        assert "required" not in schema
        assert "q" in schema["properties"]
        assert "page" in schema["properties"]


class TestQueryParamExtraction:
    def test_extracts_query_params_via_schema(self):
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
