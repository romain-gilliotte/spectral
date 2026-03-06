"""Generic JSON utilities: serialization, simplification, schema inference."""

from cli.helpers.json._debug_format import reformat_json_lines
from cli.helpers.json._extraction import extract_json
from cli.helpers.json._schema_analysis import analyze_schema
from cli.helpers.json._schema_inference import infer_schema
from cli.helpers.json._serialization import compact, minified
from cli.helpers.json._simplification import truncate_json

__all__ = [
    "analyze_schema",
    "compact",
    "extract_json",
    "infer_schema",
    "minified",
    "reformat_json_lines",
    "truncate_json",
]
