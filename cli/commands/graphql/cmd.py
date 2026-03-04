"""CLI command group for GraphQL analysis."""

from __future__ import annotations

import click

from cli.helpers.console import console


@click.group("graphql")
def graphql_cmd() -> None:
    """GraphQL analysis commands."""


@graphql_cmd.command()
@click.argument("app_name")
@click.option(
    "-o", "--output", required=True,
    help="Output base name (produces <name>.graphql).",
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
    """Analyze captures for an app and produce a GraphQL SDL schema."""
    from cli.commands.analyze.cmd import run_analysis

    result, output_base = run_analysis(
        app_name, output, model, debug, skip_enrich, protocol_filter="graphql",
    )

    for branch_output in result.outputs:
        out_path = output_base.with_suffix(branch_output.file_extension)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        artifact = branch_output.artifact
        if isinstance(artifact, dict):
            # Shouldn't happen for GraphQL but handle gracefully
            import yaml

            with open(out_path, "w") as f:
                yaml.dump(
                    artifact, f,
                    default_flow_style=False, sort_keys=False, allow_unicode=True,
                )
        else:
            with open(out_path, "w") as f:
                f.write(str(artifact))

        console.print(f"[green]{branch_output.label} written to {out_path}[/green]")

    if not result.outputs:
        console.print("[yellow]No GraphQL traces found in the capture bundle.[/yellow]")
