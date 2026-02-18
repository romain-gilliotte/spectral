"""Tests for schema inference utilities."""

from cli.analyze.schemas import (
    _detect_format,
    _infer_type,
    _infer_type_from_values,
    extract_query_params,
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
        assert set(schema["required"]) == {"name", "age"}

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
        assert "name" in schema.get("required", [])
        assert "email" not in schema.get("required", [])

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
        assert _detect_format(["2024-01-15T10:30:00Z", "2024-02-20T14:00:00Z"]) == "date-time"

    def test_date_only(self):
        assert _detect_format(["2024-01-15", "2024-02-20"]) == "date"

    def test_email(self):
        assert _detect_format(["alice@example.com", "bob@test.org"]) == "email"

    def test_uuid(self):
        assert _detect_format([
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "11111111-2222-3333-4444-555555555555",
        ]) == "uuid"

    def test_uri(self):
        assert _detect_format(["https://example.com/page1", "https://example.com/page2"]) == "uri"

    def test_no_format(self):
        assert _detect_format(["hello", "world"]) is None

    def test_non_string_values(self):
        assert _detect_format([42, 100]) is None


class TestExtractQueryParams:
    def test_extracts_with_type_and_format(self):
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
        params = extract_query_params(traces)
        assert "id" in params
        assert params["id"]["type"] == "string"
        assert params["id"]["format"] == "uuid"
        assert params["id"]["required"] is True
        assert len(params["id"]["values"]) == 2

    def test_integer_type(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/search?page=1", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/search?page=2", 200, 2000),
        ]
        params = extract_query_params(traces)
        assert params["page"]["type"] == "integer"
        assert params["page"]["format"] is None

    def test_optional_param(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/search?q=hello&page=1", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/search?q=world", 200, 2000),
        ]
        params = extract_query_params(traces)
        assert params["q"]["required"] is True
        assert params["page"]["required"] is False
