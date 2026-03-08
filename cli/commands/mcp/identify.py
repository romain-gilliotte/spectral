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
from cli.helpers.http import sanitize_headers
from cli.helpers.json import minified, truncate_json
import cli.helpers.llm as llm
from cli.helpers.prompt import load, render


async def identify_capabilities(input: IdentifyInput) -> ToolCandidate | None:
    """Evaluate a single trace to decide if it represents a useful capability.

    Returns a ToolCandidate if useful, None otherwise.
    No tools are passed to the LLM — this is a lightweight call.
    """
    target = input.target_trace

    # Format target trace request details inline
    request_details = format_request_details(target)

    # Format existing tools list
    existing_tools_text = ""
    if input.existing_tools:
        existing_tools_text = "\n\n## Already-built tools (do NOT duplicate)\n" + "\n".join(
            f"- **{t.name}**: {t.description} ({t.request.method} {t.request.path})"
            for t in input.existing_tools
        )

    prompt = render(
        "mcp-identify-user.j2",
        existing_tools_text=existing_tools_text,
        target_trace_id=target.meta.id,
        request_details=request_details,
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


def format_request_details(trace: Trace) -> str:
    """Format full request details for inline display in the prompt."""
    parts: list[str] = []
    parts.append(f"**{trace.meta.request.method} {trace.meta.request.url}**")
    parts.append(f"Status: {trace.meta.response.status}")

    # Sanitized request headers
    headers = sanitize_headers(
        {h.name: h.value for h in trace.meta.request.headers}
    )
    if headers:
        header_lines = ", ".join(f"{k}: {v}" for k, v in headers.items())
        parts.append(f"Headers: {header_lines}")

    # Request body (truncated)
    if trace.request_body:
        try:
            body: Any = json.loads(trace.request_body)
            truncated = truncate_json(body, max_keys=15)
            parts.append(f"Request body: {minified(truncated)}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raw = trace.request_body.decode(errors="replace")[:500]
            parts.append(f"Request body (raw): {raw}")

    return "\n".join(parts)
