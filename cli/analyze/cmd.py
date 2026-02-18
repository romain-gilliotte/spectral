"""CLI command for the analyze stage."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from cli.console import console


@click.command()
@click.argument("capture_path", type=click.Path(exists=True))
@click.option(
    "-o", "--output", required=True, help="Output file path for the API spec (.json)"
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
    """Analyze a capture bundle and produce an enriched API spec."""
    import anthropic

    from cli.analyze.pipeline import build_spec
    from cli.capture.loader import load_bundle

    console.print(f"[bold]Loading capture bundle:[/bold] {capture_path}")
    bundle = load_bundle(capture_path)
    console.print(
        f"  Loaded {len(bundle.traces)} traces, "
        f"{len(bundle.ws_connections)} WS connections, "
        f"{len(bundle.contexts)} contexts"
    )

    client = anthropic.AsyncAnthropic(max_retries=3)

    def on_progress(msg: str) -> None:
        console.print(f"  {msg}")

    console.print(f"[bold]Analyzing with LLM ({model})...[/bold]")
    spec = asyncio.run(
        build_spec(
            bundle,
            client=client,
            model=model,
            source_filename=Path(capture_path).name,
            on_progress=on_progress,
            enable_debug=debug,
            skip_enrich=skip_enrich,
        )
    )
    console.print(f"  Found {len(spec.protocols.rest.endpoints)} endpoints")

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(spec.model_dump_json(indent=2, by_alias=True))
    console.print(f"[green]API spec written to {output}[/green]")
