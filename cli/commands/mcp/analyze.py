"""MCP pipeline: greedy per-trace identification then tool building."""

from __future__ import annotations

import asyncio

import click

from cli.commands.capture.types import CaptureBundle
from cli.commands.mcp.build_tool import build_tool
from cli.commands.mcp.identify import identify_capabilities
from cli.commands.mcp.types import (
    IdentifyInput,
    McpPipelineResult,
    ToolBuildInput,
)
from cli.formats.mcp_tool import ToolDefinition
from cli.helpers.console import console
from cli.helpers.context import build_shared_context
from cli.helpers.detect_base_url import detect_base_url
import cli.helpers.llm as llm
from cli.helpers.storage import (
    list_captures,
    load_app_bundle,
    write_tools,
)

_MAX_ITERATIONS = 200


async def build_mcp_tools(
    bundle: CaptureBundle,
    app_name: str,
    skip_enrich: bool = False,
) -> McpPipelineResult:
    """Build MCP tool definitions from a capture bundle."""

    # Step 1: Detect base URL
    console.print("  Detecting API base URL (LLM)...")
    base_url = await detect_base_url(bundle, app_name)
    console.print(f"    API base URL: {base_url}")

    # Step 2: Filter traces
    total_before = len(bundle.traces)
    filtered_bundle = bundle.filter_traces(
        lambda t: t.meta.request.url.startswith(base_url)
    )
    console.print(
        f"    Kept {len(filtered_bundle.traces)}/{total_before} traces under {base_url}"
    )

    # Build system context (shared across identify + build_tool for prompt caching)
    system_context = build_shared_context(bundle, base_url)

    # Step 3: Greedy per-trace identification + build loop
    console.print("  Identifying capabilities and building tools...")
    tools: list[ToolDefinition] = []
    remaining_bundle = filtered_bundle
    iterations = 0

    while remaining_bundle.traces and iterations < _MAX_ITERATIONS:
        iterations += 1
        target = remaining_bundle.traces[0]

        # Lightweight: is this trace useful?
        candidate = await identify_capabilities(
            IdentifyInput(
                bundle=remaining_bundle,
                base_url=base_url,
                target_trace=target,
                existing_tools=tools,
                system_context=system_context,
            )
        )

        if candidate is None:
            console.print(f"    Evaluating {target.meta.id}... skip")
            remaining_bundle = remaining_bundle.filter_traces(
                lambda t: t.meta.id != target.meta.id
            )
            continue

        # Full build with investigation tools
        console.print(
            f"    Evaluating {target.meta.id}... useful \u2192 building {candidate.name}"
        )
        build_result = await build_tool(
            ToolBuildInput(
                candidate=candidate,
                bundle=filtered_bundle,
                base_url=base_url,
                existing_tools=tools,
                system_context=system_context,
            )
        )
        tools.append(build_result.tool)

        # Remove consumed traces
        consumed = set(build_result.consumed_trace_ids)
        before_count = len(remaining_bundle.traces)
        remaining_bundle = remaining_bundle.filter_traces(
            lambda t: t.meta.id not in consumed
        )
        removed = before_count - len(remaining_bundle.traces)
        console.print(
            f"      \u2192 {build_result.tool.name}: {build_result.tool.request.method} "
            f"{build_result.tool.request.path} "
            f"(removed {removed} traces, {len(remaining_bundle.traces)} remaining)"
        )

    console.print(f"  Extracted {len(tools)} tool(s).")

    return McpPipelineResult(
        tools=tools,
        base_url=base_url,
    )


@click.command()
@click.argument("app_name")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
@click.option(
    "--skip-enrich",
    is_flag=True,
    default=False,
    help="Skip LLM enrichment step (business context, glossary, etc.)",
)
def analyze_cmd(app_name: str, debug: bool, skip_enrich: bool) -> None:
    """Generate MCP tool definitions from captures."""
    from cli.helpers.llm._client import load_model

    cap_count = len(list_captures(app_name))
    console.print(f"[bold]Loading captures for app:[/bold] {app_name}")
    bundle = load_app_bundle(app_name)
    console.print(
        f"  Loaded {cap_count} capture(s): "
        f"{len(bundle.traces)} traces, "
        f"{len(bundle.ws_connections)} WS connections, "
        f"{len(bundle.contexts)} contexts"
    )

    llm.init_debug(debug=debug)

    console.print(f"[bold]Generating MCP tools with LLM ({load_model()})...[/bold]")
    result = asyncio.run(
        build_mcp_tools(
            bundle,
            app_name,
            skip_enrich=skip_enrich,
        )
    )

    write_tools(app_name, result.tools)
    console.print(f"[green]Wrote {len(result.tools)} tool(s) to storage[/green]")

    for tool in result.tools:
        console.print(
            f"  Tool: {tool.name} — {tool.request.method} {tool.request.path}"
        )
