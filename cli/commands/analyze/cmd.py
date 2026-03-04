"""CLI command for the analyze stage."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import click
import yaml

from cli.helpers.console import console


@click.command()
@click.argument("app_name")
@click.option(
    "-o", "--output", required=False, default=None,
    help="Output base name (produces <name>.yaml and/or <name>.graphql). Required unless --mcp is used.",
)
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
@click.option(
    "--mcp",
    is_flag=True,
    default=False,
    help="Generate MCP tool definitions instead of OpenAPI/SDL",
)
def analyze(
    app_name: str, output: str | None, model: str, debug: bool, skip_enrich: bool, mcp: bool
) -> None:
    """Analyze captures for an app and produce an API spec."""
    import cli.helpers.llm as llm
    from cli.helpers.storage import list_captures, load_app_bundle

    if not mcp and not output:
        raise click.UsageError("Missing option '-o' / '--output'. Required unless --mcp is used.")

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

    if mcp:
        _analyze_mcp(app_name, bundle, model, on_progress, skip_enrich)
        return

    from cli.commands.analyze.pipeline import build_spec

    console.print(f"[bold]Analyzing with LLM ({model})...[/bold]")
    result = asyncio.run(
        build_spec(
            bundle,
            source_filename=app_name,
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

    # Strip any extension from the output name so it's a pure base name
    assert output is not None  # guaranteed by UsageError guard above
    output_base = Path(output)
    output_base = output_base.parent / output_base.stem

    # Write each branch output
    for branch_output in result.outputs:
        out_path = output_base.with_suffix(branch_output.file_extension)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        artifact = branch_output.artifact
        if isinstance(artifact, dict):
            # Dict artifact (e.g. OpenAPI) → YAML
            with open(out_path, "w") as f:
                yaml.dump(
                    artifact, f,
                    default_flow_style=False, sort_keys=False, allow_unicode=True,
                )
        else:
            # String artifact (e.g. SDL) → write as-is
            with open(out_path, "w") as f:
                f.write(str(artifact))

        console.print(f"[green]{branch_output.label} written to {out_path}[/green]")

        # REST-specific: Restish config
        if branch_output.protocol == "rest" and isinstance(artifact, dict):
            endpoint_count = len(artifact.get("paths", {}))
            console.print(f"  Found {endpoint_count} REST paths")

            from cli.commands.analyze.restish import generate_restish_entry
            from cli.commands.analyze.steps.types import AuthInfo

            restish_entry = generate_restish_entry(
                base_url=result.base_url,
                spec_path=out_path.resolve(),
                auth=AuthInfo(),
                auth_helper_path=None,
            )
            restish_path = output_base.with_suffix(".restish.json")
            with open(restish_path, "w") as f:
                json.dump(restish_entry, f, indent=2)
                f.write("\n")
            console.print(f"[green]Restish config written to {restish_path}[/green]")

            # Print Restish usage instructions
            api_name = output_base.stem
            console.print()
            console.print("[bold]Restish setup:[/bold]")
            console.print(
                f"  Merge [cyan]{restish_path}[/cyan] into "
                f"~/.config/restish/apis.json under the key [cyan]{api_name}[/cyan]"
            )
            placeholders = _find_placeholders(restish_entry)
            if placeholders:
                console.print(f"  Fill in placeholder values: {', '.join(placeholders)}")

    if not result.outputs:
        console.print("[yellow]No API traces found in the capture bundle.[/yellow]")


def _analyze_mcp(
    app_name: str,
    bundle: object,
    model: str,
    on_progress: Callable[[str], None] | None,
    skip_enrich: bool,
) -> None:
    """Run the MCP tool generation pipeline."""
    from cli.commands.analyze.steps.mcp.pipeline import build_mcp_tools
    from cli.commands.capture.types import CaptureBundle
    import cli.helpers.llm as llm
    from cli.helpers.storage import (
        update_app_meta,
        write_tools,
    )

    typed_bundle = CaptureBundle(**vars(bundle)) if not isinstance(bundle, CaptureBundle) else bundle

    console.print(f"[bold]Generating MCP tools with LLM ({model})...[/bold]")
    result = asyncio.run(
        build_mcp_tools(
            typed_bundle,
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


def _find_placeholders(entry: dict[str, object]) -> list[str]:
    """Find placeholder values like <TOKEN> in a restish config entry."""
    serialized = json.dumps(entry)
    return re.findall(r"<[A-Z_]+>", serialized)
