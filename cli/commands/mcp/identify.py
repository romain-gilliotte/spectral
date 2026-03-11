"""Evaluate a single trace to decide if it represents a useful business capability."""

from __future__ import annotations

import json
from typing import Any

from cli.commands.capture.types import Trace
from cli.commands.mcp.types import (
    IdentifyInput,
    IdentifyResponse,
    ToolCandidate,
)
import cli.helpers.llm as llm
from cli.helpers.prompt import load, render


async def identify_capabilities(input: IdentifyInput) -> ToolCandidate | None:
    """Evaluate a single trace to decide if it represents a useful capability.

    Returns a ToolCandidate if useful, None otherwise.
    No tools are passed to the LLM — this is a lightweight call.
    """
    target = input.target_trace

    request_body = _parse_request_body(target)

    prompt = render(
        "mcp-identify-user.j2",
        existing_tools=input.existing_tools,
        target=target,
        request_body=request_body,
    )

    conv = llm.Conversation(
        system=[input.system_context, load("mcp-identify-instructions.j2")],
        label=f"identify_{target.meta.id}",
        max_tokens=1024,
    )
    result = await conv.ask_json(prompt, IdentifyResponse)

    if not result.useful:
        return None

    if not result.name or not result.description:
        return None

    return ToolCandidate(
        name=result.name,
        description=result.description,
        trace_ids=[target.meta.id],
    )


def _parse_request_body(trace: Trace) -> Any | None:
    """Parse the request body as JSON, returning None on failure."""
    if not trace.request_body:
        return None
    try:
        return json.loads(trace.request_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
