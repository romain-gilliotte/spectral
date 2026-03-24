"""MCP pipeline: greedy per-trace identification then tool building."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from cli.commands.mcp.types import BuildToolResponse
from cli.formats.mcp_tool import ToolDefinition
from cli.helpers.console import console
from cli.helpers.llm import Conversation, current_model, init_debug
from cli.helpers.prompt import render
from cli.helpers.storage import list_captures, load_app_bundle, write_tools

if TYPE_CHECKING:
    from cli.commands.capture.types import CaptureBundle, Trace

_MAX_ITERATIONS = 200


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
        f"{len(bundle.contexts)} contexts"
    )

    init_debug(debug=debug)

    console.print(f"[bold]Generating MCP tools with LLM ({current_model()})...[/bold]")
    tools = _consume_traces(bundle)

    write_tools(app_name, tools)
    console.print(f"[green]Wrote {len(tools)} tool(s) to storage[/green]")

    for tool in tools:
        console.print(f"  Tool: {tool.name} — {tool.request.method} {tool.request.url}")


def _consume_traces(bundle: CaptureBundle) -> list[ToolDefinition]:
    """Build MCP tool definitions from a capture bundle."""

    tools: list[ToolDefinition] = []
    remaining_traces: list[Trace] = bundle.traces
    total = len(remaining_traces)

    while remaining_traces:
        trace = remaining_traces.pop(0)
        idx = total - len(remaining_traces)
        console.print(
            f"  [{idx}/{total}] Building tool from trace "
            f"[bold]{trace.meta.id}[/bold] "
            f"({trace.meta.request.method} {trace.meta.request.url})..."
        )
        try:
            build_result = _build_tool(bundle, trace, tools)

            if build_result.tool:
                tools.append(build_result.tool)
                console.print(f"    [green]→ {build_result.tool.name}[/green]")
            else:
                console.print("    [dim]→ skipped (no tool produced)[/dim]")

            consumed = (build_result.useless_traces_found or []) + (
                build_result.tool.example_traces if build_result.tool else []
            )
            if consumed:
                before = len(remaining_traces)
                remaining_traces = [
                    t for t in remaining_traces if t.meta.id not in consumed
                ]
                merged = before - len(remaining_traces)
                if merged:
                    console.print(
                        f"    [dim]→ consumed {merged} additional trace(s)[/dim]"
                    )

        except Exception as e:
            console.print(
                f"    [red]Error building tool for trace {trace.meta.id}: {e}[/red]"
            )
            continue

    return tools


def _build_tool(
    bundle: CaptureBundle, trace: Trace, existing_tools: list[ToolDefinition]
) -> BuildToolResponse:
    """Build an MCP tool definition from a single trace, given the shared system context."""

    conversation = Conversation(
        system=render("mcp-build-tool-system.md.j2"),
        tool_names=["query_traces"],
        bundle=bundle,
        max_iterations=_MAX_ITERATIONS,
        label=f"build:{trace.meta.id}",
    )

    return conversation.ask_json(
        render("mcp-build-tool-user.md.j2", trace=trace, existing_tools=existing_tools),
        response_model=BuildToolResponse,
    )
