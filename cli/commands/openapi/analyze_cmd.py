"""CLI command: spectral openapi analyze."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml

from cli.commands.capture.types import CaptureBundle
from cli.commands.openapi.analyze import rest_analyze
from cli.helpers.console import console
from cli.helpers.correlator import correlate
from cli.helpers.detect_base_url import detect_base_urls
import cli.helpers.llm as llm
from cli.helpers.storage import list_captures, load_app_bundle


@click.command()
@click.argument("app_name")
@click.option(
    "-o",
    "--output",
    required=True,
    help="Output base name (produces <name>.yaml).",
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
    """Analyze captures for an app and produce an OpenAPI spec."""
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

    console.print(
        f"[bold]Analyzing with LLM ({llm.current_model()})...[/bold]"
    )
    openapi_dict = _run_openapi(bundle, app_name, skip_enrich)

    output_base = Path(output)
    output_base = output_base.parent / output_base.stem
    out_path = output_base.with_suffix(".yaml")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w") as f:
        yaml.dump(
            openapi_dict,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

    console.print(f"[green]OpenAPI 3.1 spec written to {out_path}[/green]")
    endpoint_count = len(openapi_dict.get("paths", {}))
    console.print(f"  Found {endpoint_count} REST paths")


def _run_openapi(
    bundle: CaptureBundle, app_name: str, skip_enrich: bool
) -> dict[str, Any]:
    base_urls = detect_base_urls(bundle, app_name)
    if len(base_urls) > 1:
        base_url = click.prompt(
            "Multiple API base URLs detected. Pick one to analyze",
            type=click.Choice(base_urls),
        )
    else:
        base_url = base_urls[0]
    console.print(f"  API base URL: {base_url}")
    rest_traces = [t for t in bundle.traces if t.meta.request.url.startswith(base_url)]
    console.print(
        f"  Kept {len(rest_traces)}/{len(bundle.traces)} traces under {base_url}"
    )

    correlations = correlate(bundle)

    openapi_dict = rest_analyze(
        rest_traces,
        base_url=base_url,
        app_name=(
            bundle.manifest.app.name + " API"
            if bundle.manifest.app.name
            else "Discovered API"
        ),
        source_filename=app_name,
        correlations=correlations,
        skip_enrich=skip_enrich,
    )
    return openapi_dict
