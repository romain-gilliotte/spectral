"""Investigation tools for MCP pipeline LLM steps.

Provides tools for the LLM to inspect traces, infer request schemas,
and query traces via jq expressions.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any, cast
from urllib.parse import urlparse

import jq

from cli.commands.capture.types import Context, Trace
from cli.helpers.http import sanitize_headers
from cli.helpers.json import infer_schema, minified, truncate_json
from cli.helpers.llm_tools import INVESTIGATION_TOOLS, TOOL_EXECUTORS


def make_inspect_trace_tool() -> dict[str, Any]:
    return {
        "name": "inspect_trace",
        "description": (
            "Get the full request and response details for a specific trace, "
            "including headers and decoded body content (JSON or text). "
            "Use this to examine login endpoints, token responses, OTP flows, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trace_id": {
                    "type": "string",
                    "description": "The trace ID (e.g., 't_0001').",
                },
            },
            "required": ["trace_id"],
        },
    }


def execute_inspect_trace(inp: dict[str, Any], index: dict[str, Trace]) -> str:
    trace = index.get(inp["trace_id"])
    if trace is None:
        return f"Trace {inp['trace_id']} not found"

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
        # Re-truncate with tighter limits to stay under budget
        if trace.response_body:
            try:
                result["response_body"] = truncate_json(
                    json.loads(trace.response_body), max_keys=10, max_depth=2
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        serialized = minified(result)
    return serialized


def _make_inspect_request_tool() -> dict[str, Any]:
    return {
        "name": "inspect_request",
        "description": (
            "Get request-side details for a trace: method, URL, headers, "
            "and request body. Does NOT include the response. "
            "Use this first to understand what an endpoint expects. "
            "Only use inspect_trace if you also need the response body."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trace_id": {
                    "type": "string",
                    "description": "The trace ID (e.g., 't_0001').",
                },
            },
            "required": ["trace_id"],
        },
    }


def _execute_inspect_request(inp: dict[str, Any], index: dict[str, Trace]) -> str:
    trace = index.get(inp["trace_id"])
    if trace is None:
        return f"Trace {inp['trace_id']} not found"

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


def _make_infer_request_schema_tool() -> dict[str, Any]:
    return {
        "name": "infer_request_schema",
        "description": (
            "Merge request bodies from the given trace IDs into an annotated JSON Schema. "
            "Shows which fields vary (parameters) vs stay the same (fixed values) "
            "across traces, with up to 5 observed values per field."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trace_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of trace IDs whose request bodies to merge.",
                },
            },
            "required": ["trace_ids"],
        },
    }


def _execute_infer_request_schema(inp: dict[str, Any], index: dict[str, Trace]) -> str:
    trace_ids: list[str] = inp["trace_ids"]
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


_QUERY_TRACES_MAX_OUTPUT = 8000


def _make_query_traces_tool() -> dict[str, Any]:
    return {
        "name": "query_traces",
        "description": (
            "Run a jq expression against all traces. "
            "Each trace is an object with fields: id, method, url, path, "
            "status, request_headers, request_body, response_body. "
            "The input is the full array of traces. "
            "Use select() to filter, .field to extract, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "A jq expression to run against the trace array.",
                },
            },
            "required": ["expression"],
        },
    }


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


def _execute_query_traces(inp: dict[str, Any], traces: list[Trace]) -> str:
    expression: str = inp.get("expression", "")
    if not expression:
        return "The 'expression' parameter is required."

    records = [_build_trace_record(t) for t in traces]

    try:
        compiled = jq.compile(expression)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    except ValueError as exc:
        return f"Invalid jq expression: {exc}"

    results: list[Any] = compiled.input(records).all()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    output = minified(results)

    if len(output) > _QUERY_TRACES_MAX_OUTPUT:
        return (
            f"Output too large ({len(output)} chars). "
            "Write a more selective query — extract only the fields you need, "
            "or use select() to narrow down traces."
        )

    return output


def _make_inspect_context_tool() -> dict[str, Any]:
    return {
        "name": "inspect_context",
        "description": (
            "Get full details for a UI context event: action, element "
            "(tag, text, selector, attributes), page (url, title), "
            "and rich page content (headings, navigation, main text, "
            "forms, tables, alerts)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "context_id": {
                    "type": "string",
                    "description": "The context ID (e.g., 'c_0001').",
                },
            },
            "required": ["context_id"],
        },
    }


def _execute_inspect_context(inp: dict[str, Any], index: dict[str, Context]) -> str:
    ctx = index.get(inp["context_id"])
    if ctx is None:
        return f"Context {inp['context_id']} not found"

    result: dict[str, Any] = {
        "action": ctx.meta.action,
        "element": {
            "tag": ctx.meta.element.tag,
            "text": ctx.meta.element.text,
            "selector": ctx.meta.element.selector,
            "attributes": ctx.meta.element.attributes,
        },
        "page": {
            "url": ctx.meta.page.url,
            "title": ctx.meta.page.title,
        },
    }
    if ctx.meta.page.content is not None:
        content = ctx.meta.page.content
        result["page_content"] = truncate_json(
            {
                "headings": content.headings,
                "navigation": content.navigation,
                "main_text": content.main_text,
                "forms": content.forms,
                "tables": content.tables,
                "alerts": content.alerts,
            },
            max_keys=20,
        )
    return minified(result)


def make_mcp_tools(
    traces: list[Trace],
    contexts: list[Context] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Callable[[dict[str, Any]], str]]]:
    """Build the full set of investigation tools for MCP pipeline LLM steps.

    Returns ``(tool_definitions, executors)`` for use with ``llm.ask()``.
    When *contexts* is provided, includes the ``inspect_context`` tool.
    """
    trace_index = {t.meta.id: t for t in traces}

    tools: list[dict[str, Any]] = list(INVESTIGATION_TOOLS) + [
        _make_inspect_request_tool(),
        make_inspect_trace_tool(),
        _make_infer_request_schema_tool(),
        _make_query_traces_tool(),
    ]

    executors: dict[str, Callable[[dict[str, Any]], str]] = {
        **TOOL_EXECUTORS,
        "inspect_request": lambda inp: _execute_inspect_request(inp, trace_index),
        "inspect_trace": lambda inp: execute_inspect_trace(inp, trace_index),
        "infer_request_schema": lambda inp: _execute_infer_request_schema(
            inp, trace_index
        ),
        "query_traces": lambda inp: _execute_query_traces(inp, traces),
    }

    if contexts is not None:
        context_index = {c.meta.id: c for c in contexts}
        tools.append(_make_inspect_context_tool())
        executors["inspect_context"] = lambda inp: _execute_inspect_context(
            inp, context_index
        )

    return tools, executors
