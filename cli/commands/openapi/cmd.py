"""CLI command group for OpenAPI (REST) analysis."""

from __future__ import annotations

from typing import Any

import click
import yaml

from cli.helpers.console import console


@click.group("openapi")
def openapi() -> None:
    """OpenAPI (REST) analysis commands."""


@openapi.command()
@click.argument("app_name")
@click.option(
    "-o", "--output", required=True,
    help="Output base name (produces <name>.yaml).",
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
def analyze(app_name: str, output: str, model: str, debug: bool, skip_enrich: bool) -> None:
    """Analyze captures for an app and produce an OpenAPI spec."""
    import asyncio
    from datetime import datetime, timezone
    from pathlib import Path

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

    from cli.commands.openapi.analyze import rest_analyze
    from cli.helpers.correlator import correlate
    from cli.helpers.detect_base_url import detect_base_url

    async def _run() -> dict[str, Any]:
        base_url = await detect_base_url(bundle, app_name)
        on_progress(f"API base URL: {base_url}")
        rest_traces = [t for t in bundle.traces if t.meta.request.url.startswith(base_url)]
        on_progress(f"Kept {len(rest_traces)}/{len(bundle.traces)} traces under {base_url}")

        correlations = correlate(bundle)

        openapi_dict = await rest_analyze(
            rest_traces,
            base_url=base_url,
            app_name=(bundle.manifest.app.name + " API" if bundle.manifest.app.name else "Discovered API"),
            source_filename=app_name,
            correlations=correlations,
            on_progress=on_progress,
            skip_enrich=skip_enrich,
        )
        return openapi_dict

    console.print(f"[bold]Analyzing with LLM ({model})...[/bold]")
    openapi_dict = asyncio.run(_run())

    inp_tok, out_tok = llm.get_usage()
    if inp_tok or out_tok:
        cache_read, cache_create = llm.get_cache_usage()
        cost = llm.estimate_cost(model, inp_tok, out_tok, cache_read, cache_create)
        cost_str = f" (~${cost:.2f})" if cost is not None else ""
        console.print(f"  LLM token usage: {inp_tok:,} input, {out_tok:,} output{cost_str}")

    output_base = Path(output)
    output_base = output_base.parent / output_base.stem
    out_path = output_base.with_suffix(".yaml")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w") as f:
        yaml.dump(
            openapi_dict, f,
            default_flow_style=False, sort_keys=False, allow_unicode=True,
        )

    console.print(f"[green]OpenAPI 3.1 spec written to {out_path}[/green]")
    endpoint_count = len(openapi_dict.get("paths", {}))
    console.print(f"  Found {endpoint_count} REST paths")
