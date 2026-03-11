"""LLM tool: inspect full request+response details for a trace."""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import RunContext

from cli.commands.capture.types import Trace
from cli.helpers.http import sanitize_headers
from cli.helpers.json import minified, truncate_json
from cli.helpers.llm.tools._deps import ToolDeps


def execute(trace_id: str, index: dict[str, Trace]) -> str:
    """Core logic, importable for direct testing."""
    trace = index.get(trace_id)
    if trace is None:
        return f"Trace {trace_id} not found"

    result: dict[str, Any] = {
        "method": trace.meta.request.method,
        "url": trace.meta.request.url,
        "status": trace.meta.response.status,
        "request_headers": sanitize_headers(
            {h.name: h.value for h in trace.meta.request.headers}
        ),
        "response_headers": sanitize_headers(
            {h.name: h.value for h in trace.meta.response.headers}
        ),
    }
    if trace.request_body:
        try:
            result["request_body"] = truncate_json(
                json.loads(trace.request_body), max_keys=30
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            result["request_body_raw"] = trace.request_body.decode(errors="replace")[
                :2000
            ]
    if trace.response_body:
        try:
            result["response_body"] = truncate_json(
                json.loads(trace.response_body), max_keys=30
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            result["response_body_raw"] = trace.response_body.decode(errors="replace")[
                :2000
            ]
    serialized = minified(result)
    if len(serialized) > 4000:
        if trace.response_body:
            try:
                result["response_body"] = truncate_json(
                    json.loads(trace.response_body), max_keys=10, max_depth=2
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        serialized = minified(result)
    return serialized


def inspect_trace(ctx: RunContext[ToolDeps], trace_id: str) -> str:
    """Get full request and response details for a trace.

    Includes headers and decoded body content (JSON or text).
    Use this to examine login endpoints, token responses, OTP flows, etc.

    Args:
        trace_id: The trace ID (e.g., 't_0001').
    """
    return execute(trace_id, ctx.deps.trace_index)
