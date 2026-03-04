"""MCP pipeline: batch identification then sequential tool building."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from cli.commands.analyze.correlator import correlate
from cli.commands.analyze.steps.analyze_auth import (
    AnalyzeAuthStep,
    detect_auth_mechanical,
)
from cli.commands.analyze.steps.detect_base_url import DetectBaseUrlStep
from cli.commands.analyze.steps.extract_pairs import ExtractPairsStep
from cli.commands.analyze.steps.filter_traces import FilterTracesStep
from cli.commands.analyze.steps.mcp.build_tool import BuildToolStep
from cli.commands.analyze.steps.mcp.cleanup import CleanupTracesStep
from cli.commands.analyze.steps.mcp.identify import IdentifyCapabilitiesStep
from cli.commands.analyze.steps.mcp.types import (
    CleanupInput,
    IdentifyInput,
    McpPipelineResult,
    ToolBuildInput,
)
from cli.commands.analyze.steps.types import AuthInfo, TracesWithBaseUrl
from cli.commands.capture.types import CaptureBundle
from cli.formats.mcp_tool import ToolDefinition


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
    correlations = correlate(bundle)

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

    # Step 5: Batch identification — single LLM call
    progress("Identifying capabilities (LLM)...")
    identify_step = IdentifyCapabilitiesStep()
    candidates = await identify_step.run(
        IdentifyInput(
            correlations=correlations,
            remaining_traces=filtered,
            base_url=base_url,
        )
    )
    progress(f"  Found {len(candidates)} candidate(s).")

    # Step 6: Sequential build + cleanup for each candidate
    tools: list[ToolDefinition] = []
    remaining = list(filtered)

    for i, candidate in enumerate(candidates, 1):
        if not remaining:
            progress("  Trace pool empty — stopping.")
            break

        progress(
            f"  [{i}/{len(candidates)}] Building tool: {candidate.name} "
            f"({len(candidate.trace_ids)} example traces)"
        )

        build_step = BuildToolStep()
        tool = await build_step.run(
            ToolBuildInput(
                candidate=candidate,
                traces=filtered,
                base_url=base_url,
                existing_tools=tools,
            )
        )
        tools.append(tool)

        # Cleanup: remove matching traces
        cleanup_step = CleanupTracesStep()
        before_count = len(remaining)
        remaining = await cleanup_step.run(
            CleanupInput(
                traces=remaining,
                tool_definition=tool,
                base_url=base_url,
            )
        )
        removed = before_count - len(remaining)
        progress(
            f"    → {tool.name}: {tool.request.method} {tool.request.path} "
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
            progress("  Auth script generation failed — skipping")

    return McpPipelineResult(
        tools=tools,
        base_url=base_url,
        auth=auth,
        auth_acquire_script=auth_acquire_script,
    )
