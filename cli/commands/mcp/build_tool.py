"""Build a complete tool definition from a candidate (LLM)."""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded

from cli.commands.capture.types import CaptureBundle, Trace
from cli.commands.mcp.types import (
    BuildToolResponse,
    ToolCandidate,
)
from cli.formats.mcp_tool import ToolDefinition
from cli.helpers.console import console
import cli.helpers.llm as llm
from cli.helpers.prompt import load, render


def _parse_request_body(trace: Trace) -> Any | None:
    """Parse the request body as JSON, returning None on failure."""
    if not trace.request_body:
        return None
    try:
        return json.loads(trace.request_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def build_tool(
    candidate: ToolCandidate,
    bundle: CaptureBundle,
    existing_tools: list[ToolDefinition],
    system_context: str,
) -> BuildToolResponse:
    """Build a complete MCP tool definition using LLM with investigation tools.

    Returns a BuildToolResponse (tool definition + consumed trace IDs).
    """
    target_trace = next(
        (t for t in bundle.traces if t.meta.id in candidate.trace_ids),
        None,
    )
    request_body = _parse_request_body(target_trace) if target_trace else None

    prompt = render(
        "mcp-build-tool-user.j2",
        candidate_name=candidate.name,
        candidate_description=candidate.description,
        existing_tools=existing_tools,
        target_trace=target_trace,
        request_body=request_body,
    )

    tool_names = [
        "decode_base64", "decode_url", "decode_jwt",
        "inspect_request", "inspect_trace",
        "infer_request_schema", "query_traces",
    ]
    if bundle.contexts:
        tool_names.append("inspect_context")

    conv = llm.Conversation(
        system=[system_context, load("mcp-build-tool-instructions.j2")],
        label=f"build_tool_{candidate.name}",
        tool_names=tool_names,
        bundle=bundle,
        max_tokens=8192,
    )
    try:
        return conv.ask_json(prompt, BuildToolResponse)
    except (UnexpectedModelBehavior, UsageLimitExceeded) as exc:
        console.print(f"      [yellow]⚠ LLM returned invalid output for {candidate.name}, skipping ({exc})[/yellow]")
        return BuildToolResponse(tool=None, consumed_trace_ids=candidate.trace_ids)
