"""LLM tool: inspect request-side details for a trace."""

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
    }
    if trace.request_body:
        try:
            result["request_body"] = truncate_json(
                json.loads(trace.request_body), max_keys=20
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            result["request_body_raw"] = trace.request_body.decode(errors="replace")[
                :1000
            ]
    return minified(result)


def inspect_request(ctx: RunContext[ToolDeps], trace_id: str) -> str:
    """Get request-side details for a trace: method, URL, headers, and request body.

    Does NOT include the response. Use this first to understand what an endpoint
    expects. Only use inspect_trace if you also need the response body.

    Args:
        trace_id: The trace ID (e.g., 't_0001').
    """
    return execute(trace_id, ctx.deps.trace_index)
