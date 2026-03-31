"""Generate and validate the acquire_token() function using LLM.

The LLM receives trace summaries, discovers the auth mechanism itself,
and generates an ``acquire_token()`` function.  The generated script is
tested interactively: ``acquire_token()`` is called (prompting the user
for credentials), and if it fails the error is fed back to the LLM on
the same conversation for correction.

Raises ``NoAuthDetected`` if the LLM concludes there is no auth.

Also contains the ``spectral auth analyze-acquire`` Click command.
"""

from __future__ import annotations

import click

from cli.helpers.auth import (
    extract_script,
    get_acquire_instructions,
    get_auth_rules,
    save_auth_result,
    validate_function,
)
from cli.helpers.console import console
from cli.helpers.context import build_timeline
from cli.helpers.llm import Conversation, init_debug
from cli.helpers.storage import auth_script_path, load_app_bundle, resolve_app


@click.command("analyze-acquire")
@click.argument("app_name")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def analyze_acquire(app_name: str, debug: bool) -> None:
    """Analyze auth mechanism and generate an acquire_token() script."""

    resolve_app(app_name)
    init_debug(debug=debug)

    bundle = load_app_bundle(app_name)

    conv = Conversation(
        system=[build_timeline(bundle), get_auth_rules()],
        max_tokens=8192,
        max_iterations=20,
        label="generate_auth_acquire",
        tool_names=["decode_base64", "decode_url", "decode_jwt", "query_traces"],
        bundle=bundle,
    )

    # ── Generate, validate, and fix acquire_token ─────────────────────
    console.print("[bold]Generating acquire script...[/bold]")
    initial_text = conv.ask_text(get_acquire_instructions())
    validated = validate_function(
        conv, extract_script, initial_text=initial_text, fn="acquire_token"
    )
    if validated is None:
        console.print("[dim]No working auth script produced.[/dim]")
        return
    script, acquire_result = validated

    # Save the working script
    script_path = auth_script_path(app_name)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script)

    # Persist the token so `spectral auth login` is not needed
    if isinstance(acquire_result, dict):
        save_auth_result(app_name, acquire_result)  # type: ignore[arg-type]
        console.print("[green]Token saved.[/green]")

    console.print(f"[green]Acquire script written to {script_path}[/green]")
