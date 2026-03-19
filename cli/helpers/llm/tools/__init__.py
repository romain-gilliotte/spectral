"""Tool registry for LLM tool-use via PydanticAI.

Each tool module exposes a callable suitable for ``pydantic_ai.tools.Tool``.
Stateful tools receive a ``RunContext[ToolDeps]``; stateless ones are plain functions.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pydantic_ai.tools import Tool

from cli.helpers.llm.tools import (
    _decode_base64,
    _decode_jwt,
    _decode_url,
    _infer_request_schema,
    _inspect_context,
    _inspect_request,
    _inspect_trace,
    _query_traces,
)
from cli.helpers.llm.tools._deps import ToolDeps

# Registry: tool name → (callable, takes_ctx)
_REGISTRY: dict[str, tuple[Callable[..., Any], bool]] = {
    "decode_base64": (_decode_base64.decode_base64, False),
    "decode_url": (_decode_url.decode_url, False),
    "decode_jwt": (_decode_jwt.decode_jwt, False),
    "inspect_trace": (_inspect_trace.inspect_trace, True),
    "inspect_request": (_inspect_request.inspect_request, True),
    "inspect_context": (_inspect_context.inspect_context, True),
    "infer_request_schema": (_infer_request_schema.infer_request_schema, True),
    "query_traces": (_query_traces.query_traces, True),
}


def make_tools(
    names: Sequence[str],
) -> list[Tool[ToolDeps]]:
    """Build PydanticAI ``Tool`` objects for the given tool names."""
    tools: list[Tool[ToolDeps]] = []

    for name in names:
        entry = _REGISTRY.get(name)
        if entry is None:
            raise ValueError(f"Unknown tool: {name!r}. Available: {sorted(_REGISTRY)}")
        fn, takes_ctx = entry
        tools.append(Tool(fn, takes_ctx=takes_ctx))

    return tools


def describe_tools(names: Sequence[str]) -> dict[str, str]:
    """Return ``{name: first_docstring_line}`` for the given tool names."""
    result: dict[str, str] = {}
    for name in names:
        entry = _REGISTRY.get(name)
        if entry is None:
            raise ValueError(f"Unknown tool: {name!r}. Available: {sorted(_REGISTRY)}")
        fn = entry[0]
        doc = (fn.__doc__ or "").strip().split("\n")[0]
        result[name] = doc
    return result
