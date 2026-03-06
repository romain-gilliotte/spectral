"""Build a complete tool definition from a candidate (LLM)."""

from __future__ import annotations

import re
from typing import Any, cast

from cli.commands.mcp.identify import format_request_details
from cli.commands.mcp.investigation import make_mcp_tools
from cli.commands.mcp.types import (
    BuildToolResponse,
    ToolBuildInput,
    ToolBuildResult,
)
import cli.helpers.llm as llm

BUILD_TOOL_INSTRUCTIONS = """\
You are analyzing captured HTTP traffic from a web application to identify and document API capabilities as MCP tools.

## Your task

1. Use `query_traces` to find ALL traces that serve the same business purpose as this candidate.
   Think about what makes traces "the same operation" based on the API pattern:
   - REST-like API: same URL pattern, different params
   - Persisted GraphQL (Apollo APQ): same URL but different hash in request body — each hash is a different operation
   - Single-endpoint RPC: same URL but routing via a field in the request body (e.g., `action`, `method`, `operationName`)
   Inspect trace bodies to decide, not just URLs.
2. Use `inspect_request` to examine traces (method, URL, headers, request body)
3. Use `infer_request_schema` with the trace IDs to see which request fields vary vs stay the same
4. Only use `inspect_trace` if you specifically need the response body
5. Build the complete tool definition AND list all consumed trace IDs

## Tool definition format

The tool definition must be a JSON object with these fields:
- `name`: snake_case identifier matching the candidate name
- `description`: what this tool does in business terms (for the LLM to understand when to use it)
- `parameters`: JSON Schema object describing the tool's input parameters
- `request`: HTTP request template with:
  - `method`: HTTP method
  - `path`: relative path from base URL, may contain {param} segments (e.g. "/api/users/{user_id}")
  - `headers`: fixed headers (optional, object)
  - `query`: query parameters (optional, object — values can be literals or {"$param": "name"})
  - `body`: request body template (optional, object — values can be literals or {"$param": "name"})
  - `content_type`: body content type (optional, defaults to "application/json")
- `requires_auth`: boolean — set to `true` if the traces carry authentication (Authorization header, auth cookies, API key headers, etc.), `false` if the endpoint is publicly accessible without credentials

## Templating rules

- **Fixed values**: values that are the same across all traces → put them as literals in the template
- **Variable values**: values that differ across traces → define as parameters and use {"$param": "param_name"} in the template
- **Path parameters**: use {param_name} in the path for variable URL segments
- Every `$param` reference must match a property in `parameters`
- Every path `{param}` must match a property in `parameters`

## Rules

- Remove the base URL prefix from the path (the server will prepend it)
- Include only parameters the LLM should provide — omit fixed API version headers, client IDs, etc.
- Do NOT include authentication headers (Authorization, Cookie, x-authorization, etc.) in the request template. Auth is injected separately at runtime. The `headers` field only supports literal string values, not `$param` references.
- Give each parameter a clear description so the LLM knows what to provide
- Mark required parameters in the JSON Schema `required` array

## Output format

Return a JSON object with two fields:
- `tool`: the complete tool definition (as described above)
- `consumed_trace_ids`: array of ALL trace IDs that belong to this operation (not just the example traces — include every trace you found via query_traces)

Example: {"tool": {...tool definition...}, "consumed_trace_ids": ["t_0001", "t_0002", ...]}"""


async def build_tool(input: ToolBuildInput) -> ToolBuildResult:
    """Build a complete MCP tool definition using LLM with investigation tools.

    Input: ToolBuildInput (candidate, traces, base_url, existing_tools, system_context).
    Output: ToolBuildResult (tool definition + consumed trace IDs).
    """
    candidate = input.candidate

    # Format target trace request details inline
    target_trace = next(
        (t for t in input.traces if t.meta.id in candidate.trace_ids),
        None,
    )
    target_details = ""
    if target_trace is not None:
        target_details = f"\n\n## Target request ({candidate.trace_ids[0]})\n\n{format_request_details(target_trace)}"

    existing_tools_hint = ""
    if input.existing_tools:
        existing_tools_hint = "\n\nExisting tools (for reference, do not duplicate):\n" + "\n".join(
            f"  - {t.name}: {t.description} ({t.request.method} {t.request.path})"
            for t in input.existing_tools
        )

    prompt = f"""## Candidate: {candidate.name}
- Description: {candidate.description}
{existing_tools_hint}
{target_details}"""

    tools, executors = make_mcp_tools(input.traces, contexts=input.contexts)

    result = await llm.ask(
        prompt,
        system=[input.system_context, BUILD_TOOL_INSTRUCTIONS],
        label=f"build_tool_{candidate.name}",
        tools=tools,
        executors=executors,
        max_tokens=8192,
        response_model=BuildToolResponse,
    )

    tool_result = ToolBuildResult(tool=result.tool, consumed_trace_ids=result.consumed_trace_ids)
    _validate_tool_result(tool_result)
    return tool_result


def _validate_tool_result(output: ToolBuildResult) -> None:
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
