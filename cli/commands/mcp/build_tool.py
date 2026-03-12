"""Build a complete tool definition from a candidate (LLM)."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from cli.commands.capture.types import CaptureBundle, Trace
from cli.commands.mcp.types import (
    BuildToolResponse,
    ToolCandidate,
)
from cli.formats.mcp_tool import ToolDefinition
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


async def build_tool(
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
    result = await conv.ask_json(prompt, BuildToolResponse)

    if result.tool is not None:
        _validate_tool_result(result)
    return result


def _validate_tool_result(output: BuildToolResponse) -> None:
    assert output.tool is not None
    tool = output.tool
    # Validate path params match parameters
    path_params = set(re.findall(r"\{(\w+)\}", tool.request.path))
    param_properties = set(tool.parameters.get("properties", {}).keys())

    missing_path = path_params - param_properties
    if missing_path:
        raise ValueError(
            f"Path params not in parameters: {missing_path}",
        )

    # Validate $param references exist in parameters
    body_params = _collect_param_refs(tool.request.body)
    query_params = _collect_param_refs(tool.request.query)
    all_refs = body_params | query_params | path_params

    missing_refs = all_refs - param_properties
    if missing_refs:
        raise ValueError(
            f"$param references not in parameters: {missing_refs}",
        )


def _collect_param_refs(obj: object) -> set[str]:
    """Collect all $param reference names from a template object."""
    refs: set[str] = set()
    if isinstance(obj, dict):
        d = cast(dict[str, Any], obj)
        if len(d) == 1 and "$param" in d:
            refs.add(str(d["$param"]))
        else:
            for v in d.values():
                refs.update(_collect_param_refs(v))
    elif isinstance(obj, list):
        items = cast(list[Any], obj)
        for item in items:
            refs.update(_collect_param_refs(item))
    return refs
