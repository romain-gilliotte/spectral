"""MCP pipeline: greedy per-trace identification then tool building."""

from __future__ import annotations

from collections.abc import Callable

from cli.commands.analyze.steps.context import build_shared_context
from cli.commands.analyze.steps.detect_base_url import DetectBaseUrlStep
from cli.commands.analyze.steps.extract_pairs import ExtractPairsStep
from cli.commands.analyze.steps.filter_traces import FilterTracesStep
from cli.commands.analyze.steps.mcp.build_tool import BuildToolStep
from cli.commands.analyze.steps.mcp.identify import IdentifyCapabilitiesStep
from cli.commands.analyze.steps.mcp.types import (
    IdentifyInput,
    McpPipelineResult,
    ToolBuildInput,
)
from cli.commands.analyze.steps.types import TracesWithBaseUrl
from cli.commands.capture.types import CaptureBundle, Trace
from cli.formats.mcp_tool import ToolDefinition

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

    # Step 1: Extract pairs
    extract_step = ExtractPairsStep()
    pairs = await extract_step.run(bundle)

    # Step 2: Detect base URL
    progress("Detecting API base URL (LLM)...")
    detect_url_step = DetectBaseUrlStep(app_name=app_name)
    base_url = await detect_url_step.run(pairs)
    progress(f"  API base URL: {base_url}")

    # Step 3: Filter traces
    filter_step = FilterTracesStep()
    total_before = len(all_traces)
    filtered = await filter_step.run(
        TracesWithBaseUrl(traces=all_traces, base_url=base_url)
    )
    progress(f"  Kept {len(filtered)}/{total_before} traces under {base_url}")

    # Build system context (shared across identify + build_tool for prompt caching)
    system_context = build_shared_context(bundle, base_url)

    # Step 5: Greedy per-trace identification + build loop
    progress("Identifying capabilities and building tools...")
    tools: list[ToolDefinition] = []
    remaining: list[Trace] = list(filtered)
    contexts = list(bundle.contexts)
    iterations = 0

    while remaining and iterations < _MAX_ITERATIONS:
        iterations += 1
        target = remaining[0]

        # Lightweight: is this trace useful?
        identify_step = IdentifyCapabilitiesStep()
        candidate = await identify_step.run(
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
        build_step = BuildToolStep()
        build_result = await build_step.run(
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
