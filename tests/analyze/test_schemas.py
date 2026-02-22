"""Tests for schema inference utilities."""
# pyright: reportPrivateUsage=false

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from cli.commands.analyze.schemas import (
    _detect_format,
    _infer_type,
    _infer_type_from_values,
    infer_path_schema,
    infer_query_schema,
    infer_schema,
    resolve_map_candidates,
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
        # Intermediate objects carry observed (used for OpenAPI examples in assembly)
        assert "observed" in addr

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
        # Intermediate objects carry observed (used for OpenAPI examples in assembly)
        outer = schema["properties"]["outer"]
        assert "observed" in outer
        assert "observed" in inner

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
        # Intermediate objects carry observed (used for OpenAPI examples in assembly)
        assert "observed" in prop

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


class TestDynamicKeyDetection:
    def test_date_keys_detected(self):
        samples = [
            {
                "2025-01-01": 100,
                "2025-02-01": 200,
                "2025-03-01": 300,
                "2025-04-01": 400,
                "2025-05-01": 500,
            }
        ]
        schema = infer_schema(samples)
        assert "additionalProperties" in schema
        assert "properties" not in schema
        assert schema["x-key-pattern"] == "date"
        assert schema["additionalProperties"]["type"] == "integer"
        assert len(schema["x-key-examples"]) == 5

    def test_year_keys_detected(self):
        samples = [
            {
                "2022": {"total": 100, "avg": 25},
                "2023": {"total": 200, "avg": 50},
                "2024": {"total": 300, "avg": 75},
                "2025": {"total": 400, "avg": 100},
            }
        ]
        schema = infer_schema(samples)
        assert "additionalProperties" in schema
        assert "properties" not in schema
        assert schema["x-key-pattern"] == "year"
        val_schema = schema["additionalProperties"]
        assert val_schema["type"] == "object"
        assert "total" in val_schema["properties"]
        assert "avg" in val_schema["properties"]

    def test_numeric_id_keys_detected(self):
        samples = [
            {
                "706001": "active",
                "706002": "inactive",
                "706003": "active",
            }
        ]
        schema = infer_schema(samples)
        assert "additionalProperties" in schema
        assert schema["x-key-pattern"] == "numeric-id"
        assert schema["additionalProperties"]["type"] == "string"

    def test_uuid_keys_detected(self):
        samples = [
            {
                "a1b2c3d4-e5f6-7890-abcd-ef1234567890": 1,
                "11111111-2222-3333-4444-555555555555": 2,
                "22222222-3333-4444-5555-666666666666": 3,
            }
        ]
        schema = infer_schema(samples)
        assert "additionalProperties" in schema
        assert schema["x-key-pattern"] == "uuid"

    def test_below_threshold_not_detected(self):
        """Two numeric keys are below the minimum threshold — stay as properties."""
        samples = [{"100": "a", "200": "b"}]
        schema = infer_schema(samples)
        assert "properties" in schema
        assert "additionalProperties" not in schema

    def test_mixed_types_not_detected(self):
        """Keys match a pattern but values have different types — stay as properties."""
        samples = [
            {
                "2025-01-01": 100,
                "2025-02-01": "hello",
                "2025-03-01": 300,
            }
        ]
        schema = infer_schema(samples)
        assert "properties" in schema
        assert "additionalProperties" not in schema

    def test_non_matching_keys_not_detected(self):
        """Regular field names should not trigger dynamic key detection."""
        samples = [{"name": "Alice", "email": "a@b.com", "age": 30}]
        schema = infer_schema(samples)
        assert "properties" in schema
        assert "additionalProperties" not in schema

    def test_nested_dynamic_keys(self):
        """Dynamic keys nested inside a regular object property."""
        samples = [
            {
                "data": {
                    "2025-01-01": 100,
                    "2025-02-01": 200,
                    "2025-03-01": 300,
                }
            }
        ]
        schema = infer_schema(samples)
        assert "properties" in schema
        data_prop = schema["properties"]["data"]
        assert data_prop["type"] == "object"
        assert "additionalProperties" in data_prop
        assert data_prop["x-key-pattern"] == "date"

    def test_key_examples_limited(self):
        """More than 5 keys should produce at most 5 x-key-examples."""
        samples = [{f"2025-{m:02d}-01": m for m in range(1, 13)}]
        schema = infer_schema(samples)
        assert "additionalProperties" in schema
        assert len(schema["x-key-examples"]) <= 5

    def test_value_schema_merged(self):
        """Values from different keys are merged into a unified schema."""
        samples = [
            {
                "2023": {"total": 100},
                "2024": {"total": 200, "count": 5},
                "2025": {"total": 300, "count": 10},
            }
        ]
        schema = infer_schema(samples)
        assert "additionalProperties" in schema
        val_schema = schema["additionalProperties"]
        assert val_schema["type"] == "object"
        assert "total" in val_schema["properties"]
        assert "count" in val_schema["properties"]

    def test_prefixed_uuid_keys_detected(self):
        """Prefixed UUID keys like journey-<uuid> should be detected."""
        samples = [
            {
                "journey-fd5d0e39-1234-5678-abcd-ef1234567890": {"id": 1},
                "journey-5877976c-abcd-1234-5678-abcdef123456": {"id": 2},
                "fare-a1b2c3d4-e5f6-7890-abcd-ef1234567890": {"id": 3},
            }
        ]
        schema = infer_schema(samples)
        assert "additionalProperties" in schema
        assert schema["x-key-pattern"] == "prefixed-uuid"

    def test_hex_id_keys_detected(self):
        """40-char hex hashes (SHA-1) should be detected as hex-id."""
        samples = [
            {
                "c202a8d532e84f5ab1e9d3c5a7f6e8d2b4a1c3e5": "val1",
                "a8db3ba5cc46f7e2d1b9a3c5e7f6d8b2a4c1e3f5": "val2",
                "f1e2d3c4b5a697081234567890abcdef12345678": "val3",
            }
        ]
        schema = infer_schema(samples)
        assert "additionalProperties" in schema
        assert schema["x-key-pattern"] == "hex-id"

    def test_short_hex_not_detected(self):
        """Hex strings under 20 chars should not be detected as hex-id."""
        samples = [
            {
                "abc123": "val1",
                "def456": "val2",
                "789abc": "val3",
            }
        ]
        schema = infer_schema(samples)
        assert "properties" in schema
        assert "additionalProperties" not in schema

    def test_single_hex_id_detected(self):
        """A single 40-char hex key is enough to trigger hex-id detection."""
        samples = [
            {
                "87b3bf6d86db3c23bda9321ac4699132dfbc9f28": {
                    "id": "87b3bf6d86db3c23bda9321ac4699132dfbc9f28",
                    "name": "Train",
                }
            }
        ]
        schema = infer_schema(samples)
        assert "additionalProperties" in schema
        assert schema["x-key-pattern"] == "hex-id"

    def test_single_uuid_key_detected(self):
        """A single UUID key is enough to trigger uuid detection."""
        samples = [
            {
                "a1b2c3d4-e5f6-7890-abcd-ef1234567890": {"status": "active"}
            }
        ]
        schema = infer_schema(samples)
        assert "additionalProperties" in schema
        assert schema["x-key-pattern"] == "uuid"


class TestStructuralAnnotation:
    def test_structural_candidate_annotated(self):
        """5+ keys with same-shape object values should get x-map-candidate."""
        samples = [
            {
                f"key-{i}": {"id": i, "name": f"item-{i}", "active": True}
                for i in range(6)
            }
        ]
        schema = infer_schema(samples)
        assert "x-map-candidate" in schema
        assert "properties" in schema  # properties preserved
        candidate = schema["x-map-candidate"]
        assert len(candidate["keys"]) <= 10
        assert "id" in candidate["shared_properties"]
        assert "name" in candidate["shared_properties"]

    def test_structural_ignores_scalars(self):
        """5+ keys with scalar values should not be annotated."""
        samples = [
            {f"key-{i}": f"value-{i}" for i in range(6)}
        ]
        schema = infer_schema(samples)
        assert "x-map-candidate" not in schema
        assert "properties" in schema

    def test_structural_below_threshold(self):
        """4 keys same shape should not be annotated (below _MIN_STRUCTURAL_KEYS)."""
        samples = [
            {
                f"key-{i}": {"id": i, "name": f"item-{i}"}
                for i in range(4)
            }
        ]
        schema = infer_schema(samples)
        assert "x-map-candidate" not in schema

    def test_structural_low_overlap(self):
        """5+ keys with <50% property overlap should not be annotated."""
        samples = [
            {
                "key-0": {"a": 1, "b": 2},
                "key-1": {"c": 3, "d": 4},
                "key-2": {"e": 5, "f": 6},
                "key-3": {"g": 7, "h": 8},
                "key-4": {"i": 9, "j": 10},
            }
        ]
        schema = infer_schema(samples)
        assert "x-map-candidate" not in schema


class TestResolveMapCandidates:
    @pytest.mark.asyncio
    async def test_resolve_confirmed_map(self):
        """LLM confirms is_map → properties collapsed to additionalProperties."""
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "key-0": {"type": "object", "properties": {"id": {"type": "integer", "observed": [0]}, "name": {"type": "string", "observed": ["item-0"]}}, "observed": [{"id": 0, "name": "item-0"}]},
                "key-1": {"type": "object", "properties": {"id": {"type": "integer", "observed": [1]}, "name": {"type": "string", "observed": ["item-1"]}}, "observed": [{"id": 1, "name": "item-1"}]},
            },
            "x-map-candidate": {
                "keys": ["key-0", "key-1", "key-2", "key-3", "key-4"],
                "shared_properties": ["id", "name"],
                "extra_properties": [],
            },
        }

        mock_ask = AsyncMock(return_value='[{"group": 1, "is_map": true}]')
        with patch("cli.commands.analyze.schemas.llm") as mock_llm:
            mock_llm.ask = mock_ask
            mock_llm.extract_json = __import__("cli.helpers.llm", fromlist=["extract_json"]).extract_json
            await resolve_map_candidates([schema])

        assert "additionalProperties" in schema
        assert "properties" not in schema
        assert schema["x-key-pattern"] == "dynamic"
        assert "x-map-candidate" not in schema

    @pytest.mark.asyncio
    async def test_resolve_denied_map(self):
        """LLM denies is_map → annotation removed, properties kept."""
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "config": {"type": "object", "properties": {"a": {"type": "string"}}, "observed": [{"a": "x"}]},
                "status": {"type": "object", "properties": {"a": {"type": "string"}}, "observed": [{"a": "y"}]},
            },
            "x-map-candidate": {
                "keys": ["config", "status", "meta", "info", "extra"],
                "shared_properties": ["a"],
                "extra_properties": [],
            },
        }

        mock_ask = AsyncMock(return_value='[{"group": 1, "is_map": false}]')
        with patch("cli.commands.analyze.schemas.llm") as mock_llm:
            mock_llm.ask = mock_ask
            mock_llm.extract_json = __import__("cli.helpers.llm", fromlist=["extract_json"]).extract_json
            await resolve_map_candidates([schema])

        assert "properties" in schema
        assert "additionalProperties" not in schema
        assert "x-map-candidate" not in schema

    @pytest.mark.asyncio
    async def test_resolve_no_candidates_skips_llm(self):
        """No x-map-candidate → no LLM call."""
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }

        mock_ask = AsyncMock()
        with patch("cli.commands.analyze.schemas.llm") as mock_llm:
            mock_llm.ask = mock_ask
            await resolve_map_candidates([schema])

        mock_ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_nested_candidates(self):
        """Candidate inside a nested property is correctly found and resolved."""
        inner: dict[str, Any] = {
            "type": "object",
            "properties": {
                "k0": {"type": "object", "properties": {"id": {"type": "integer", "observed": [0]}}, "observed": [{"id": 0}]},
                "k1": {"type": "object", "properties": {"id": {"type": "integer", "observed": [1]}}, "observed": [{"id": 1}]},
            },
            "x-map-candidate": {
                "keys": ["k0", "k1", "k2", "k3", "k4"],
                "shared_properties": ["id"],
                "extra_properties": [],
            },
        }
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "data": inner,
            },
        }

        mock_ask = AsyncMock(return_value='[{"group": 1, "is_map": true}]')
        with patch("cli.commands.analyze.schemas.llm") as mock_llm:
            mock_llm.ask = mock_ask
            mock_llm.extract_json = __import__("cli.helpers.llm", fromlist=["extract_json"]).extract_json
            await resolve_map_candidates([schema])

        # The inner schema should be collapsed
        data_prop = schema["properties"]["data"]
        assert "additionalProperties" in data_prop
        assert "x-map-candidate" not in data_prop
        assert data_prop["x-key-pattern"] == "dynamic"
