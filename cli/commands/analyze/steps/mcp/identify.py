"""Step: Evaluate a single trace to decide if it represents a useful business capability."""

from __future__ import annotations

import json
from typing import Any

from cli.commands.analyze.steps.base import Step
from cli.commands.analyze.steps.mcp.types import (
    IdentifyInput,
    IdentifyResponse,
    ToolCandidate,
)
from cli.commands.analyze.utils import sanitize_headers, truncate_json
from cli.commands.capture.types import Trace
import cli.helpers.llm as llm

IDENTIFY_INSTRUCTIONS = """\
You are analyzing captured HTTP traffic from a web application to identify and document API capabilities as MCP tools.

## Your task

Does this trace represent a useful **business capability** (something a user can do with this API: search, create, view, update, delete, etc.)?

Reason about the **actual content** of the request — the URL, headers, and especially the request body. The same URL can serve completely different purposes depending on the body content (e.g. a single `/graphql` endpoint, or an RPC endpoint where the `action` field determines the operation).

Ignore:
- Static assets, config/init requests, analytics, tracking, translation endpoints
- Health checks, version checks, feature flags
- Anything already covered by an existing tool listed above

If this trace is useful, return: {"useful": true, "name": "tool_name_snake_case", "description": "What this does in business terms"}
If not useful, return: {"useful": false}"""


class IdentifyCapabilitiesStep(Step[IdentifyInput, ToolCandidate | None]):
    """Evaluate a single trace to decide if it represents a useful capability.

    Returns a ToolCandidate if useful, None otherwise.
    No tools are passed to the LLM — this is a lightweight call.
    """

    name = "identify_capabilities"

    async def _execute(self, input: IdentifyInput) -> ToolCandidate | None:
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

        prompt = f"""{existing_tools_text}

## Target trace: {target.meta.id}

{request_details}"""

        result = await llm.ask(
            prompt,
            system=[input.system_context, IDENTIFY_INSTRUCTIONS],
            label=f"identify_{target.meta.id}",
            max_tokens=1024,
            response_model=IdentifyResponse,
        )

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
            parts.append(f"Request body: {llm.compact_json(truncated)}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raw = trace.request_body.decode(errors="replace")[:500]
            parts.append(f"Request body (raw): {raw}")

    return "\n".join(parts)
