"""MCP pipeline: greedy per-trace identification then tool building."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from urllib.parse import urlparse

from cli.commands.analyze.steps.analyze_auth import (
    AnalyzeAuthStep,
    detect_auth_mechanical,
)
from cli.commands.analyze.steps.detect_base_url import DetectBaseUrlStep
from cli.commands.analyze.steps.extract_pairs import ExtractPairsStep
from cli.commands.analyze.steps.filter_traces import FilterTracesStep
from cli.commands.analyze.steps.mcp.build_tool import BuildToolStep
from cli.commands.analyze.steps.mcp.identify import (
    IdentifyCapabilitiesStep,
    trace_timeline_line,
)
from cli.commands.analyze.steps.mcp.types import (
    IdentifyInput,
    McpPipelineResult,
    ToolBuildInput,
)
from cli.commands.analyze.steps.types import AuthInfo, TracesWithBaseUrl
from cli.commands.capture.types import CaptureBundle, Trace
from cli.formats.mcp_tool import ToolDefinition

_MAX_ITERATIONS = 200


def _build_timeline_text(
    bundle: CaptureBundle, base_url: str
) -> str:
    """Build a chronological timeline string from the bundle's timeline events."""
    parsed_base = urlparse(base_url)
    base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
    base_path = parsed_base.path.rstrip("/")

    trace_index = {t.meta.id: t for t in bundle.traces}
    context_index = {c.meta.id: c for c in bundle.contexts}

    lines: list[str] = []
    for event in bundle.timeline.events:
        if event.type == "context":
            ctx = context_index.get(event.ref)
            if ctx is None:
                continue
            text = ctx.meta.element.text or ctx.meta.element.selector
            lines.append(
                f"\U0001f5b1 [{ctx.meta.action}] \"{text}\" on {ctx.meta.page.url}"
            )
        elif event.type == "trace":
            trace = trace_index.get(event.ref)
            if trace is None:
                continue
            lines.append(trace_timeline_line(trace, base_origin, base_path))

    return "\n".join(lines)


async def build_mcp_tools(
    bundle: CaptureBundle,
    app_name: str,
    on_progress: Callable[[str], None] | None = None,
    skip_enrich: bool = False,
) -> McpPipelineResult:
    """Build MCP tool definitions from a capture bundle.

    Returns McpPipelineResult with tools, base_url, auth, and optional auth script.
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    all_traces = list(bundle.traces)

    # Step 1: Extract pairs
    extract_step = ExtractPairsStep()
    pairs = await extract_step.run(bundle)

    # Step 2: Detect base URL
    progress("Detecting API base URL (LLM)...")
    detect_url_step = DetectBaseUrlStep()
    base_url = await detect_url_step.run(pairs)
    progress(f"  API base URL: {base_url}")

    # Step 3: Filter traces
    filter_step = FilterTracesStep()
    total_before = len(all_traces)
    filtered = await filter_step.run(
        TracesWithBaseUrl(traces=all_traces, base_url=base_url)
    )
    progress(f"  Kept {len(filtered)}/{total_before} traces under {base_url}")

    # Step 4: Auth analysis (parallel with tool building)
    async def _auth() -> AuthInfo:
        auth_step = AnalyzeAuthStep()
        try:
            return await auth_step.run(all_traces)
        except Exception:
            return detect_auth_mechanical(all_traces)

    auth_task = asyncio.create_task(_auth())

    # Build system context (shared across identify + build_tool for prompt caching)
    timeline_text = _build_timeline_text(bundle, base_url)
    system_context = f"""You are analyzing captured HTTP traffic from a web application to identify and document API capabilities as MCP tools.

## Base URL
{base_url}

## Session timeline
{timeline_text}"""

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

    # Resolve auth
    auth = await auth_task

    # Generate auth script if needed
    auth_acquire_script: str | None = None
    needs_script = (
        auth.type in ("bearer_token", "cookie")
        and auth.login_config is not None
        and not skip_enrich
    )
    if needs_script:
        from cli.commands.analyze.steps.mcp.generate_auth import (
            GenerateMcpAuthScriptInput,
            GenerateMcpAuthScriptStep,
        )

        progress("Generating auth script (LLM)...")
        try:
            script_step = GenerateMcpAuthScriptStep()
            auth_acquire_script = await script_step.run(
                GenerateMcpAuthScriptInput(
                    auth=auth, traces=all_traces, api_name=app_name
                )
            )
        except Exception:
            progress("  Auth script generation failed \u2014 skipping")

    return McpPipelineResult(
        tools=tools,
        base_url=base_url,
        auth=auth,
        auth_acquire_script=auth_acquire_script,
    )
