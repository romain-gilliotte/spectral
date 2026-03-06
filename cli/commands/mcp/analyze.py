"""MCP pipeline: greedy per-trace identification then tool building."""

from __future__ import annotations

from collections.abc import Callable

from cli.commands.capture.types import CaptureBundle, Trace
from cli.commands.mcp.build_tool import build_tool
from cli.commands.mcp.identify import identify_capabilities
from cli.commands.mcp.types import (
    IdentifyInput,
    McpPipelineResult,
    ToolBuildInput,
)
from cli.formats.mcp_tool import ToolDefinition
from cli.helpers.context import build_shared_context
from cli.helpers.detect_base_url import detect_base_url

_MAX_ITERATIONS = 200


async def build_mcp_tools(
    bundle: CaptureBundle,
    app_name: str,
    on_progress: Callable[[str], None] | None = None,
    skip_enrich: bool = False,
) -> McpPipelineResult:
    """Build MCP tool definitions from a capture bundle."""

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    all_traces = list(bundle.traces)

    # Step 1: Detect base URL
    progress("Detecting API base URL (LLM)...")
    base_url = await detect_base_url(bundle, app_name)
    progress(f"  API base URL: {base_url}")

    # Step 2: Filter traces
    total_before = len(all_traces)
    filtered = [t for t in all_traces if t.meta.request.url.startswith(base_url)]
    progress(f"  Kept {len(filtered)}/{total_before} traces under {base_url}")

    # Build system context (shared across identify + build_tool for prompt caching)
    system_context = build_shared_context(bundle, base_url)

    # Step 3: Greedy per-trace identification + build loop
    progress("Identifying capabilities and building tools...")
    tools: list[ToolDefinition] = []
    remaining: list[Trace] = list(filtered)
    contexts = list(bundle.contexts)
    iterations = 0

    while remaining and iterations < _MAX_ITERATIONS:
        iterations += 1
        target = remaining[0]

        # Lightweight: is this trace useful?
        candidate = await identify_capabilities(
            IdentifyInput(
                remaining_traces=remaining,
                base_url=base_url,
                target_trace=target,
                existing_tools=tools,
                system_context=system_context,
            )
        )

        if candidate is None:
            progress(f"  Evaluating {target.meta.id}... skip")
            remaining = remaining[1:]
            continue

        # Full build with investigation tools
        progress(f"  Evaluating {target.meta.id}... useful \u2192 building {candidate.name}")
        build_result = await build_tool(
            ToolBuildInput(
                candidate=candidate,
                traces=filtered,
                contexts=contexts,
                base_url=base_url,
                existing_tools=tools,
                system_context=system_context,
            )
        )
        tools.append(build_result.tool)

        # Remove consumed traces
        consumed = set(build_result.consumed_trace_ids)
        before_count = len(remaining)
        remaining = [t for t in remaining if t.meta.id not in consumed]
        removed = before_count - len(remaining)
        progress(
            f"    \u2192 {build_result.tool.name}: {build_result.tool.request.method} "
            f"{build_result.tool.request.path} "
            f"(removed {removed} traces, {len(remaining)} remaining)"
        )

    progress(f"Extracted {len(tools)} tool(s).")

    return McpPipelineResult(
        tools=tools,
        base_url=base_url,
    )
