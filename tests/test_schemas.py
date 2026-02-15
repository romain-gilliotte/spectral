"""Tests for schema inference utilities."""

from cli.analyze.schemas import (
    _build_annotated_schema,
    _detect_format,
    _infer_json_schema,
    _infer_type,
    _infer_type_from_values,
    _merge_schemas,
)


class TestBuildAnnotatedSchema:
    def test_basic_properties(self):
        samples = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        schema = _build_annotated_schema(samples)
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
        schema = _build_annotated_schema(samples)
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
        schema = _build_annotated_schema(samples)
        assert schema["properties"]["x"]["observed"] == ["a", "b"]

    def test_observed_values_max_5(self):
        samples = [{"x": i} for i in range(20)]
        schema = _build_annotated_schema(samples)
        assert len(schema["properties"]["x"]["observed"]) == 5

    def test_optional_fields(self):
        samples = [
            {"name": "Alice", "email": "a@b.com"},
            {"name": "Bob"},
        ]
        schema = _build_annotated_schema(samples)
        assert "name" in schema.get("required", [])
        assert "email" not in schema.get("required", [])

    def test_format_detection(self):
        samples = [
            {"created_at": "2024-01-15T10:30:00Z"},
            {"created_at": "2024-02-20T14:00:00Z"},
        ]
        schema = _build_annotated_schema(samples)
        assert schema["properties"]["created_at"]["format"] == "date-time"

    def test_empty_samples(self):
        schema = _build_annotated_schema([])
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


class TestMergeSchemas:
    def test_basic(self):
        samples = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        merged = _merge_schemas(samples)
        assert merged["a"]["type"] == "integer"
        assert merged["a"]["required"] is True
        assert merged["b"]["type"] == "string"

    def test_optional_key(self):
        samples = [{"a": 1, "b": 2}, {"a": 3}]
        merged = _merge_schemas(samples)
        assert merged["a"]["required"] is True
        assert merged["b"]["required"] is False
