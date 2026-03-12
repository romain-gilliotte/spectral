"""LLM tool: run a jq expression against all traces."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import jq
from pydantic_ai import RunContext

from cli.commands.capture.types import Trace
from cli.helpers.http import sanitize_headers
from cli.helpers.json import minified
from cli.helpers.llm.tools._deps import ToolDeps

_QUERY_TRACES_MAX_OUTPUT = 8000


def _build_trace_record(trace: Trace) -> dict[str, Any]:
    """Build a dict for one trace, suitable for jq processing."""
    parsed = urlparse(trace.meta.request.url)
    record: dict[str, Any] = {
        "id": trace.meta.id,
        "method": trace.meta.request.method,
        "url": trace.meta.request.url,
        "path": parsed.path,
        "status": trace.meta.response.status,
        "request_headers": sanitize_headers(
            {h.name: h.value for h in trace.meta.request.headers}
        ),
        "request_body": None,
        "response_body": None,
    }
    if trace.request_body:
        try:
            record["request_body"] = json.loads(trace.request_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    if trace.response_body:
        try:
            record["response_body"] = json.loads(trace.response_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return record


def execute(expression: str, traces: list[Trace]) -> str:
    """Core logic, importable for direct testing."""
    if not expression:
        return "The 'expression' parameter is required."

    records = [_build_trace_record(t) for t in traces]

    try:
        compiled = jq.compile(expression)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    except ValueError as exc:
        return f"Invalid jq expression: {exc}"

    try:
        results: list[Any] = compiled.input(records).all()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    except ValueError as exc:
        return f"jq runtime error: {exc}. Try a different expression."
    output = minified(results)

    if len(output) > _QUERY_TRACES_MAX_OUTPUT:
        return (
            f"Output too large ({len(output)} chars). "
            "Write a more selective query — extract only the fields you need, "
            "or use select() to narrow down traces."
        )

    return output


def query_traces(ctx: RunContext[ToolDeps], expression: str) -> str:
    """Run a jq expression against all traces.

    Each trace is an object with fields: id, method, url, path,
    status, request_headers, request_body, response_body.
    The input is the full array of traces. Use select() to filter,
    .field to extract, etc.

    Args:
        expression: A jq expression to run against the trace array.
    """
    return execute(expression, ctx.deps.traces)
