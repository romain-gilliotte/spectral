"""LLM tool: merge request bodies into an annotated JSON Schema."""

from __future__ import annotations

import json
from typing import Any, cast

from pydantic_ai import RunContext

from cli.commands.capture.types import Trace
from cli.helpers.json import minified
from cli.helpers.llm.tools._deps import ToolDeps
from cli.helpers.schema import infer_schema


def execute(trace_ids: list[str], index: dict[str, Trace]) -> str:
    """Core logic, importable for direct testing."""
    samples: list[dict[str, Any]] = []
    for tid in trace_ids:
        trace = index.get(tid)
        if trace is None:
            continue
        if trace.request_body:
            try:
                body: Any = json.loads(trace.request_body)
                if isinstance(body, dict):
                    samples.append(cast(dict[str, Any], body))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

    if not samples:
        return "No JSON request bodies found for the given trace IDs."

    schema = infer_schema(samples)
    return minified(schema)


def infer_request_schema(ctx: RunContext[ToolDeps], trace_ids: list[str]) -> str:
    """Merge request bodies from the given trace IDs into an annotated JSON Schema.

    Shows which fields vary (parameters) vs stay the same (fixed values)
    across traces, with up to 5 example values per field.

    Args:
        trace_ids: List of trace IDs whose request bodies to merge.
    """
    return execute(trace_ids, ctx.deps.trace_index)
