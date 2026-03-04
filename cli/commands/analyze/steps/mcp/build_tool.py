"""Step: Build a complete tool definition from a candidate (LLM)."""

from __future__ import annotations

import re

from cli.commands.analyze.steps.base import Step, StepValidationError
from cli.commands.analyze.steps.mcp.tools import make_mcp_tools
from cli.commands.analyze.steps.mcp.types import ToolBuildInput
from cli.formats.mcp_tool import ToolDefinition
import cli.helpers.llm as llm


class BuildToolStep(Step[ToolBuildInput, ToolDefinition]):
    """Build a complete MCP tool definition using LLM with investigation tools.

    Input: ToolBuildInput (candidate, traces, base_url, existing_tools).
    Output: ToolDefinition.
    """

    name = "build_tool"

    async def _execute(self, input: ToolBuildInput) -> ToolDefinition:
        candidate = input.candidate
        trace_ids_str = ", ".join(candidate.trace_ids)

        existing_tools_hint = ""
        if input.existing_tools:
            existing_tools_hint = "\n\nExisting tools (for reference, do not duplicate):\n" + "\n".join(
                f"  - {t.name}: {t.request.method} {t.request.path}"
                for t in input.existing_tools
            )

        prompt = f"""You are building an MCP tool definition for the "{candidate.name}" capability.

## Candidate
- Name: {candidate.name}
- Description: {candidate.description}
- Example trace IDs: {trace_ids_str}
- Base URL: {input.base_url}
{existing_tools_hint}

## Your task

1. Use `inspect_request` to examine the example traces (method, URL, headers, request body) — this is lightweight
2. Use `infer_request_schema` with the trace IDs to see which request fields vary vs stay the same
3. Use `query_traces` with a jq expression if you need to discover additional examples (e.g. `[.[] | select(.path | test("/api/search")) | .id]`)
4. Only use `inspect_trace` if you specifically need the response body (e.g. to understand the response schema)
5. Build the complete tool definition

## Tool definition format

The tool definition must be a JSON object with these fields:
- `name`: snake_case identifier (use "{candidate.name}")
- `description`: what this tool does in business terms (for the LLM to understand when to use it)
- `parameters`: JSON Schema object describing the tool's input parameters
- `request`: HTTP request template with:
  - `method`: HTTP method
  - `path`: relative path from base URL, may contain {{param}} segments (e.g. "/api/users/{{user_id}}")
  - `headers`: fixed headers (optional, object)
  - `query`: query parameters (optional, object — values can be literals or {{"$param": "name"}})
  - `body`: request body template (optional, object — values can be literals or {{"$param": "name"}})
  - `content_type`: body content type (optional, defaults to "application/json")
- `requires_auth`: boolean — set to `true` if the traces carry authentication (Authorization header, auth cookies, API key headers, etc.), `false` if the endpoint is publicly accessible without credentials

## Templating rules

- **Fixed values**: values that are the same across all traces → put them as literals in the template
- **Variable values**: values that differ across traces → define as parameters and use {{"$param": "param_name"}} in the template
- **Path parameters**: use {{param_name}} in the path for variable URL segments
- Every `$param` reference must match a property in `parameters`
- Every path `{{param}}` must match a property in `parameters`

## Rules

- Remove the base URL prefix from the path (the server will prepend it)
- Include only parameters the LLM should provide — omit fixed API version headers, client IDs, etc.
- Do NOT include authentication headers (Authorization, Cookie, x-authorization, etc.) in the request template. Auth is injected separately at runtime. The `headers` field only supports literal string values, not `$param` references.
- Give each parameter a clear description so the LLM knows what to provide
- Mark required parameters in the JSON Schema `required` array

Respond with a compact JSON object (no indentation) containing the complete tool definition."""

        tools, executors = make_mcp_tools(input.traces)

        text = await llm.ask(
            prompt,
            label=f"build_tool_{candidate.name}",
            tools=tools,
            executors=executors,
            max_tokens=8192,
        )

        data = llm.extract_json(text)
        if not isinstance(data, dict):
            raise StepValidationError(
                "Expected a JSON object for tool definition",
                {"raw": text[:500]},
            )

        return ToolDefinition.model_validate(data)

    def _validate_output(self, output: ToolDefinition) -> None:
        # Validate path params match parameters
        path_params = set(re.findall(r"\{(\w+)\}", output.request.path))
        param_properties = set(output.parameters.get("properties", {}).keys())

        missing_path = path_params - param_properties
        if missing_path:
            raise StepValidationError(
                f"Path params not in parameters: {missing_path}",
                {"missing": list(missing_path)},
            )

        # Validate $param references exist in parameters
        body_params = _collect_param_refs(output.request.body)
        query_params = _collect_param_refs(output.request.query)
        all_refs = body_params | query_params | path_params

        missing_refs = all_refs - param_properties
        if missing_refs:
            raise StepValidationError(
                f"$param references not in parameters: {missing_refs}",
                {"missing": list(missing_refs)},
            )


def _collect_param_refs(obj: object) -> set[str]:
    """Collect all $param reference names from a template object."""
    from typing import Any, cast

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
