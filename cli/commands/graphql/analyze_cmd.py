"""CLI command: spectral graphql analyze."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from cli.helpers.console import console

if TYPE_CHECKING:
    from cli.commands.capture.types import CaptureBundle


@click.command()
@click.argument("app_name")
@click.option(
    "-o", "--output", required=True,
    help="Output base name (produces <name>.graphql).",
)
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
@click.option(
    "--skip-enrich",
    is_flag=True,
    default=False,
    help="Skip LLM enrichment step (business context, glossary, etc.)",
)
def analyze(app_name: str, output: str, debug: bool, skip_enrich: bool) -> None:
    """Analyze captures for an app and produce a GraphQL SDL schema."""
    import asyncio
    from pathlib import Path

    import cli.helpers.llm as llm
    from cli.helpers.llm._client import load_model
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

    llm.init_debug(debug=debug)

    console.print(f"[bold]Analyzing with LLM ({load_model()})...[/bold]")
    sdl = asyncio.run(_run_graphql(bundle, app_name, skip_enrich))

    output_base = Path(output)
    output_base = output_base.parent / output_base.stem
    out_path = output_base.with_suffix(".graphql")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w") as f:
        f.write(sdl)

    console.print(f"[green]GraphQL SDL schema written to {out_path}[/green]")

    if not sdl.strip():
        console.print("[yellow]No GraphQL traces found in the capture bundle.[/yellow]")


async def _run_graphql(
    bundle: CaptureBundle, app_name: str, skip_enrich: bool
) -> str:
    from cli.commands.graphql.analyze import graphql_analyze
    from cli.helpers.correlator import correlate
    from cli.helpers.detect_base_url import detect_base_url

    base_url = await detect_base_url(bundle, app_name)
    console.print(f"  API base URL: {base_url}")
    gql_traces = [t for t in bundle.traces if t.meta.request.url.startswith(base_url)]
    console.print(f"  Kept {len(gql_traces)}/{len(bundle.traces)} traces under {base_url}")

    correlations = correlate(bundle)

    sdl = await graphql_analyze(
        gql_traces,
        app_name=(bundle.manifest.app.name + " API" if bundle.manifest.app.name else "Discovered API"),
        correlations=correlations,
        skip_enrich=skip_enrich,
    )
    return sdl
