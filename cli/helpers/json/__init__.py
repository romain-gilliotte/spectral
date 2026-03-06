"""Generic JSON utilities: serialization, simplification, schema inference."""

from cli.helpers.json._schema_analysis import analyze_schema
from cli.helpers.json._schema_inference import infer_schema
from cli.helpers.json._serialization import compact, minified
from cli.helpers.json._simplification import truncate_json

__all__ = ["analyze_schema", "compact", "infer_schema", "minified", "truncate_json"]
