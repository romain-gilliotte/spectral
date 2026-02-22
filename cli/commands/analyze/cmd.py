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

# Per-million-token pricing: (input_$/M, output_$/M)
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-haiku-3-5-20241022": (0.80, 4.0),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Return estimated USD cost, or None if model pricing is unknown."""
    pricing = _MODEL_PRICING.get(model)
    if pricing is None:
        return None
    inp_rate, out_rate = pricing
    return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000


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

    inp_tok, out_tok = llm.get_usage()
    if inp_tok or out_tok:
        cost = _estimate_cost(model, inp_tok, out_tok)
        cost_str = f" (~${cost:.2f})" if cost else ""
        console.print(f"  LLM token usage: {inp_tok:,} input, {out_tok:,} output{cost_str}")

    # Strip any extension from the output name so it's a pure base name
    output_base = Path(output)
    output_base = output_base.parent / output_base.stem

    # Write auth helper script (protocol-agnostic — works for REST and GraphQL)
    from cli.commands.analyze.steps.types import AuthInfo

    auth = result.auth or AuthInfo()
    auth_helper_path: str | None = None

    if result.auth_acquire_script:
        from cli.helpers.auth_framework import generate_auth_script

        login_config = auth.login_config
        credential_fields = (
            login_config.credential_fields if login_config else {}
        )
        api_name = output_base.stem

        full_script = generate_auth_script(
            acquire_source=result.auth_acquire_script,
            api_name=api_name,
            credential_fields=credential_fields,
            token_header=auth.token_header or "Authorization",
            token_prefix=auth.token_prefix or "Bearer",
        )
        helper_file = output_base.with_name(f"{output_base.stem}-auth.py")
        with open(helper_file, "w") as f:
            f.write(full_script)
        auth_helper_path = str(helper_file.resolve())
        console.print(f"[green]Auth helper written to {helper_file}[/green]")

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

            restish_entry = generate_restish_entry(
                base_url=result.base_url,
                spec_path=out_path.resolve(),
                auth=auth,
                auth_helper_path=auth_helper_path,
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

        # GraphQL-specific: auth helper usage instructions
        if branch_output.protocol == "graphql" and auth_helper_path:
            console.print()
            console.print("[bold]GraphQL auth usage:[/bold]")
            helper_name = Path(auth_helper_path).name
            console.print(
                f"  Get a token:  [cyan]python3 {helper_name}[/cyan]"
            )
            console.print(
                f"  With curl:    [cyan]curl -H \"Authorization: "
                f"{auth.token_prefix or 'Bearer'} $(python3 {helper_name})\" ...[/cyan]"
            )

    if not result.outputs:
        console.print("[yellow]No API traces found in the capture bundle.[/yellow]")


def _find_placeholders(entry: dict[str, object]) -> list[str]:
    """Find placeholder values like <TOKEN> in a restish config entry."""
    serialized = json.dumps(entry)
    return re.findall(r"<[A-Z_]+>", serialized)
