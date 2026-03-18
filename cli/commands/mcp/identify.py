"""Evaluate a single trace to decide if it represents a useful business capability."""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai.exceptions import UnexpectedModelBehavior

from cli.commands.capture.types import Trace
from cli.commands.mcp.types import (
    IdentifyResponse,
    ToolCandidate,
)
from cli.formats.mcp_tool import ToolDefinition
from cli.helpers.console import console
import cli.helpers.llm as llm
from cli.helpers.prompt import load, render


def identify_capabilities(
    target_trace: Trace,
    existing_tools: list[ToolDefinition],
    system_context: str,
) -> ToolCandidate | None:
    """Evaluate a single trace to decide if it represents a useful capability.

    Returns a ToolCandidate if useful, None otherwise.
    No tools are passed to the LLM — this is a lightweight call.
    """
    request_body = _parse_request_body(target_trace)

    prompt = render(
        "mcp-identify-user.j2",
        existing_tools=existing_tools,
        target=target_trace,
        request_body=request_body,
    )

    conv = llm.Conversation(
        system=[system_context, load("mcp-identify-instructions.j2")],
        label=f"identify_{target_trace.meta.id}",
        max_tokens=1024,
    )
    try:
        result = conv.ask_json(prompt, IdentifyResponse)
    except UnexpectedModelBehavior as exc:
        console.print(f"    [yellow]⚠ LLM returned invalid output for {target_trace.meta.id}, skipping ({exc})[/yellow]")
        return None

    if not result.useful:
        return None

    if not result.name or not result.description:
        return None

    return ToolCandidate(
        name=result.name,
        description=result.description,
        trace_ids=[target_trace.meta.id],
    )


def _parse_request_body(trace: Trace) -> Any | None:
    """Parse the request body as JSON, returning None on failure."""
    if not trace.request_body:
        return None
    try:
        return json.loads(trace.request_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
