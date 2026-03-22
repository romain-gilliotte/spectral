"""MCP pipeline: greedy per-trace identification then tool building."""

from __future__ import annotations

import click

from cli.commands.capture.types import CaptureBundle
from cli.commands.mcp.build_tool import build_tool
from cli.commands.mcp.identify import identify_capabilities
from cli.formats.mcp_tool import ToolDefinition
from cli.helpers.console import console
from cli.helpers.context import build_timeline
from cli.helpers.detect_base_url import detect_base_urls
import cli.helpers.llm as llm
from cli.helpers.storage import (
    list_captures,
    load_app_bundle,
    write_tools,
)

_MAX_ITERATIONS = 200


def build_mcp_tools(bundle: CaptureBundle, app_name: str) -> list[ToolDefinition]:
    """Build MCP tool definitions from a capture bundle."""

    # Step 1: Detect base URLs
    console.print("  Detecting API base URLs (LLM)...")
    base_urls = detect_base_urls(bundle, app_name)
    for url in base_urls:
        console.print(f"    API base URL: {url}")

    all_tools: list[ToolDefinition] = []

    for base_url in base_urls:
        # Step 2: Filter traces for this base_url
        total_before = len(bundle.traces)
        filtered_bundle = bundle.filter_traces(
            lambda t, _bu=base_url: t.meta.request.url.startswith(_bu)
        )
        console.print(
            f"    Kept {len(filtered_bundle.traces)}/{total_before} traces under {base_url}"
        )

        if not filtered_bundle.traces:
            continue

        # Build system context (shared across identify + build_tool for prompt caching)
        system_context = build_timeline(bundle)

        # Step 3: Greedy per-trace identification + build loop
        console.print("  Identifying capabilities and building tools...")
        tools: list[ToolDefinition] = []
        remaining_bundle = filtered_bundle
        iterations = 0

        while remaining_bundle.traces and iterations < _MAX_ITERATIONS:
            iterations += 1
            target = remaining_bundle.traces[0]

            # Lightweight: is this trace useful?
            candidate = identify_capabilities(
                target_trace=target,
                existing_tools=tools,
                system_context=system_context,
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
            build_result = build_tool(
                candidate=candidate,
                bundle=filtered_bundle,
                existing_tools=tools,
                system_context=system_context,
            )
            # Remove consumed traces
            consumed = set(build_result.consumed_trace_ids)
            before_count = len(remaining_bundle.traces)
            remaining_bundle = remaining_bundle.filter_traces(
                lambda t: t.meta.id not in consumed
            )
            removed = before_count - len(remaining_bundle.traces)

            if build_result.tool is not None:
                tools.append(build_result.tool)
                console.print(
                    f"      \u2192 {build_result.tool.name}: {build_result.tool.request.method} "
                    f"{build_result.tool.request.url} "
                    f"(removed {removed} traces, {len(remaining_bundle.traces)} remaining)"
                )
            else:
                console.print(
                    f"      \u2192 skipped after investigation "
                    f"(removed {removed} traces, {len(remaining_bundle.traces)} remaining)"
                )

        console.print(f"  Extracted {len(tools)} tool(s) for {base_url}.")
        all_tools.extend(tools)

    console.print(f"  Total: {len(all_tools)} tool(s).")

    return all_tools


@click.command()
@click.argument("app_name")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def analyze_cmd(app_name: str, debug: bool) -> None:
    """Generate MCP tool definitions from captures."""

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

    console.print(f"[bold]Generating MCP tools with LLM ({llm.current_model()})...[/bold]")
    tools = build_mcp_tools(bundle, app_name)

    write_tools(app_name, tools)
    console.print(f"[green]Wrote {len(tools)} tool(s) to storage[/green]")

    for tool in tools:
        console.print(
            f"  Tool: {tool.name} — {tool.request.method} {tool.request.url}"
        )
