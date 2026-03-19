"""Generate token acquisition functions using LLM.

The LLM receives trace summaries, discovers the auth mechanism itself,
and generates ``acquire_token()`` / ``refresh_token()`` functions.
Raises ``NoAuthDetected`` if the LLM concludes there is no auth.

Also contains the ``spectral auth analyze`` Click command.
"""

from __future__ import annotations

import click

from cli.helpers.auth.errors import AuthScriptInvalid
from cli.helpers.auth.generation import extract_script, get_auth_instructions
from cli.helpers.console import console
from cli.helpers.context import build_timeline
from cli.helpers.llm import Conversation, init_debug
from cli.helpers.storage import auth_script_path, load_app_bundle, resolve_app


@click.command()
@click.argument("app_name")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def analyze(app_name: str, debug: bool) -> None:
    """Analyze auth mechanism for an app and generate an auth script."""

    resolve_app(app_name)
    console.print(f"[bold]Loading captures for app:[/bold] {app_name}")
    bundle = load_app_bundle(app_name)
    console.print(f"  Loaded {len(bundle.traces)} traces")

    init_debug(debug=debug)

    conv = Conversation(
        system=[build_timeline(bundle)],
        max_tokens=8192,
        label="generate_auth_script",
        tool_names=["decode_base64", "decode_url", "decode_jwt", "inspect_trace"],
        bundle=bundle,
    )

    try:
        script = extract_script(conv.ask_text(get_auth_instructions()))

        if script is None:
            console.print()
            console.print(
                "[dim]No authentication mechanism detected in traces. "
                "No script generated.[/dim]"
            )
            return

        script_path = auth_script_path(app_name)
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script)
        console.print(f"[green]Auth script written to {script_path}[/green]")
    except AuthScriptInvalid:
        console.print(f"[red]Failed to generate auth script[/red]")
        console.print(f"[red]Run again with --debug[/red]")
