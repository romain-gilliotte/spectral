"""JSON serialization helpers for LLM prompts and debug output."""

from __future__ import annotations

import json
from typing import Any


def minified(obj: Any) -> str:
    """Serialize *obj* to compact JSON (no whitespace) for LLM prompts."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def compact(obj: Any) -> str:
    """Format *obj* as semi-compact JSON for debug readability.

    Short inner arrays/objects (<=80 chars when collapsed) are placed on a
    single line while larger structures remain indented.  Uses compact-json
    for reliable formatting.
    """
    import compact_json  # type: ignore[import-untyped]

    formatter = compact_json.Formatter()
    formatter.indent_spaces = 2
    formatter.max_inline_length = 80
    formatter.ensure_ascii = False
    return formatter.serialize(obj)
