"""CLI command group for the MCP server and tool generation."""

from __future__ import annotations

import asyncio

import click

from cli.helpers.console import console


@click.group()
def mcp() -> None:
    """MCP server and tool generation commands."""


@mcp.command()
def stdio() -> None:
    """Start the MCP server on stdio.

    Exposes all app tools from managed storage as MCP tools.
    """
    from cli.commands.mcp.server import run_server

    asyncio.run(run_server())


@mcp.command()
@click.argument("app_name")
@click.option("--model", default="claude-sonnet-4-5-20250929", help="LLM model to use")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
@click.option(
    "--skip-enrich",
    is_flag=True,
    default=False,
    help="Skip LLM enrichment step (business context, glossary, etc.)",
)
def analyze(app_name: str, model: str, debug: bool, skip_enrich: bool) -> None:
    """Generate MCP tool definitions from captures."""
    from datetime import datetime, timezone
    from pathlib import Path

    from cli.commands.analyze.cmd import run_mcp_analysis
    import cli.helpers.llm as llm
    from cli.helpers.storage import list_captures, load_app_bundle

    cap_count = len(list_captures(app_name))
    console.print(f"[bold]Loading captures for app:[/bold] {app_name}")
    bundle = load_app_bundle(app_name)
    console.print(
        f"  Loaded {cap_count} capture(s): "
        f"{len(bundle.traces)} traces, "
        f"{len(bundle.ws_connections)} WS connections, "
        f"{len(bundle.contexts)} contexts"
    )

    debug_dir = None
    if debug:
        run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        debug_dir = Path("debug") / run_ts
        debug_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"  Debug logs → {debug_dir}")

    llm.init(debug_dir=debug_dir, model=model)

    def on_progress(msg: str) -> None:
        console.print(f"  {msg}")

    run_mcp_analysis(app_name, bundle, model, on_progress, skip_enrich)
