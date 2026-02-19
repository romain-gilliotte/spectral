"""CLI command for the analyze stage."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
import yaml

from cli.helpers.console import console


@click.command()
@click.argument("capture_path", type=click.Path(exists=True))
@click.option(
    "-o", "--output", required=True, help="Output file path for the OpenAPI spec (.yaml)"
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
def analyze(
    capture_path: str, output: str, model: str, debug: bool, skip_enrich: bool
) -> None:
    """Analyze a capture bundle and produce an OpenAPI spec."""
    from cli.commands.analyze.pipeline import build_spec
    from cli.commands.capture.loader import load_bundle
    import cli.helpers.llm as llm

    console.print(f"[bold]Loading capture bundle:[/bold] {capture_path}")
    bundle = load_bundle(capture_path)
    console.print(
        f"  Loaded {len(bundle.traces)} traces, "
        f"{len(bundle.ws_connections)} WS connections, "
        f"{len(bundle.contexts)} contexts"
    )

    llm.init()

    def on_progress(msg: str) -> None:
        console.print(f"  {msg}")

    console.print(f"[bold]Analyzing with LLM ({model})...[/bold]")
    openapi = asyncio.run(
        build_spec(
            bundle,
            model=model,
            source_filename=Path(capture_path).name,
            on_progress=on_progress,
            enable_debug=debug,
            skip_enrich=skip_enrich,
        )
    )
    endpoint_count = len(openapi.get("paths", {}))
    console.print(f"  Found {endpoint_count} paths")

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(
            openapi, f, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
    console.print(f"[green]OpenAPI spec written to {output}[/green]")
