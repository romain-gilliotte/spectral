"""CLI command for the analyze stage."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import click
import yaml

from cli.helpers.console import console


@click.command()
@click.argument("capture_path", type=click.Path(exists=True))
@click.option(
    "-o", "--output", required=True, help="Output base name (produces <name>.yaml and/or <name>.graphql)"
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
    """Analyze a capture bundle and produce an API spec."""
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

    debug_dir = None
    if debug:
        run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        debug_dir = Path("debug") / run_ts
        debug_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"  Debug logs → {debug_dir}")

    llm.init(debug_dir=debug_dir, model=model)

    def on_progress(msg: str) -> None:
        console.print(f"  {msg}")

    console.print(f"[bold]Analyzing with LLM ({model})...[/bold]")
    result = asyncio.run(
        build_spec(
            bundle,
            source_filename=Path(capture_path).name,
            on_progress=on_progress,
            skip_enrich=skip_enrich,
        )
    )

    # Strip any extension from the output name so it's a pure base name
    output_base = Path(output)
    output_base = output_base.parent / output_base.stem

    # Write OpenAPI spec (REST) and Restish config
    if result.openapi is not None:
        endpoint_count = len(result.openapi.get("paths", {}))
        console.print(f"  Found {endpoint_count} REST paths")
        yaml_path = output_base.with_suffix(".yaml")
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        with open(yaml_path, "w") as f:
            yaml.dump(
                result.openapi, f, default_flow_style=False, sort_keys=False, allow_unicode=True
            )
        console.print(f"[green]OpenAPI spec written to {yaml_path}[/green]")

        # Restish config
        from cli.commands.analyze.restish import generate_restish_entry
        from cli.commands.analyze.steps.types import AuthInfo

        auth = result.auth or AuthInfo()

        # Write auth helper script if the pipeline generated one
        auth_helper_path: str | None = None
        if result.auth_helper_script:
            helper_file = output_base.with_name(f"{output_base.stem}-auth.py")
            with open(helper_file, "w") as f:
                f.write(result.auth_helper_script)
            auth_helper_path = str(helper_file.resolve())
            console.print(f"[green]Auth helper written to {helper_file}[/green]")

        restish_entry = generate_restish_entry(
            base_url=result.base_url,
            spec_path=yaml_path.resolve(),
            auth=auth,
            auth_helper_path=auth_helper_path,
        )
        restish_path = output_base.with_suffix(".restish.json")
        with open(restish_path, "w") as f:
            json.dump(restish_entry, f, indent=2)
            f.write("\n")
        console.print(f"[green]Restish config written to {restish_path}[/green]")

        # Print usage instructions
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

    # Write GraphQL SDL
    if result.graphql_sdl is not None:
        gql_path = output_base.with_suffix(".graphql")
        gql_path.parent.mkdir(parents=True, exist_ok=True)
        with open(gql_path, "w") as f:
            f.write(result.graphql_sdl)
        console.print(f"[green]GraphQL schema written to {gql_path}[/green]")

    if result.openapi is None and result.graphql_sdl is None:
        console.print("[yellow]No API traces found in the capture bundle.[/yellow]")


def _find_placeholders(entry: dict[str, object]) -> list[str]:
    """Find placeholder values like <TOKEN> in a restish config entry."""
    serialized = json.dumps(entry)
    return re.findall(r"<[A-Z_]+>", serialized)
