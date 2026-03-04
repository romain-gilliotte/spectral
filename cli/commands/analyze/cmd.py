"""Shared helpers for the analyze commands (openapi, graphql, mcp)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from cli.commands.analyze.steps.types import AnalysisResult
from cli.commands.capture.types import CaptureBundle
from cli.helpers.console import console


def run_analysis(
    app_name: str,
    output: str,
    model: str,
    debug: bool,
    skip_enrich: bool,
    protocol_filter: str | None = None,
) -> tuple[AnalysisResult, Path]:
    """Load captures, run the analysis pipeline, and return (result, output_base).

    Shared by ``openapi analyze`` and ``graphql analyze``.
    """
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

    from cli.commands.analyze.pipeline import build_spec

    console.print(f"[bold]Analyzing with LLM ({model})...[/bold]")
    result = asyncio.run(
        build_spec(
            bundle,
            source_filename=app_name,
            on_progress=on_progress,
            skip_enrich=skip_enrich,
            protocol_filter=protocol_filter,
        )
    )

    inp_tok, out_tok = llm.get_usage()
    if inp_tok or out_tok:
        cache_read, cache_create = llm.get_cache_usage()
        cost = llm.estimate_cost(model, inp_tok, out_tok, cache_read, cache_create)
        cost_str = f" (~${cost:.2f})" if cost is not None else ""
        console.print(f"  LLM token usage: {inp_tok:,} input, {out_tok:,} output{cost_str}")

    # Strip any extension from the output name so it's a pure base name
    output_base = Path(output)
    output_base = output_base.parent / output_base.stem

    return result, output_base


def run_mcp_analysis(
    app_name: str,
    bundle: CaptureBundle,
    model: str,
    on_progress: Callable[[str], None] | None,
    skip_enrich: bool,
) -> None:
    """Run the MCP tool generation pipeline."""
    from cli.commands.analyze.steps.mcp.pipeline import build_mcp_tools
    import cli.helpers.llm as llm
    from cli.helpers.storage import (
        update_app_meta,
        write_tools,
    )

    console.print(f"[bold]Generating MCP tools with LLM ({model})...[/bold]")
    result = asyncio.run(
        build_mcp_tools(
            bundle,
            app_name,
            on_progress=on_progress,
            skip_enrich=skip_enrich,
        )
    )

    inp_tok, out_tok = llm.get_usage()
    if inp_tok or out_tok:
        cache_read, cache_create = llm.get_cache_usage()
        cost = llm.estimate_cost(model, inp_tok, out_tok, cache_read, cache_create)
        cost_str = f" (~${cost:.2f})" if cost is not None else ""
        console.print(f"  LLM token usage: {inp_tok:,} input, {out_tok:,} output{cost_str}")

    # Write tools
    write_tools(app_name, result.tools)
    console.print(f"[green]Wrote {len(result.tools)} tool(s) to storage[/green]")

    # Update app.json with base_url
    update_app_meta(app_name, base_url=result.base_url)
    console.print(f"  Base URL: {result.base_url}")

    # Summary
    for tool in result.tools:
        console.print(f"  Tool: {tool.name} — {tool.request.method} {tool.request.path}")


def find_placeholders(entry: dict[str, object]) -> list[str]:
    """Find placeholder values like <TOKEN> in a restish config entry."""
    serialized = json.dumps(entry)
    return re.findall(r"<[A-Z_]+>", serialized)
