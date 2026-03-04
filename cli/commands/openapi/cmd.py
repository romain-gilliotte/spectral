"""CLI command group for OpenAPI (REST) analysis."""

from __future__ import annotations

import json

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
    from cli.commands.analyze.cmd import find_placeholders, run_analysis

    result, output_base = run_analysis(
        app_name, output, model, debug, skip_enrich, protocol_filter="rest",
    )

    for branch_output in result.outputs:
        out_path = output_base.with_suffix(branch_output.file_extension)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        artifact = branch_output.artifact
        if isinstance(artifact, dict):
            with open(out_path, "w") as f:
                yaml.dump(
                    artifact, f,
                    default_flow_style=False, sort_keys=False, allow_unicode=True,
                )
        else:
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

            api_name = output_base.stem
            console.print()
            console.print("[bold]Restish setup:[/bold]")
            console.print(
                f"  Merge [cyan]{restish_path}[/cyan] into "
                f"~/.config/restish/apis.json under the key [cyan]{api_name}[/cyan]"
            )
            placeholders = find_placeholders(restish_entry)
            if placeholders:
                console.print(f"  Fill in placeholder values: {', '.join(placeholders)}")

    if not result.outputs:
        console.print("[yellow]No REST API traces found in the capture bundle.[/yellow]")
