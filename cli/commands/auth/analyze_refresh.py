"""Generate and validate the refresh_token() function using LLM.

Reads a stored token (from ``auth extract`` or ``auth set``) that must
contain a refresh token, then asks the LLM to generate a
``refresh_token()`` function.  The generated script is validated by
calling the function with the stored refresh token.

Also contains the ``spectral auth analyze-refresh`` Click command.
"""

from __future__ import annotations

import click

from cli.helpers.auth import (
    extract_refresh_script,
    get_auth_rules,
    get_refresh_instructions,
    save_auth_result,
    validate_function,
)
from cli.helpers.console import console
from cli.helpers.context import build_timeline
from cli.helpers.llm import Conversation, init_debug
from cli.helpers.storage import (
    load_app_bundle,
    load_token,
    refresh_script_path,
    resolve_app,
)


@click.command("analyze-refresh")
@click.argument("app_name")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def analyze_refresh(app_name: str, debug: bool) -> None:
    """Analyze refresh mechanism and generate a refresh_token() script.

    Requires a stored token with a refresh_token field (from ``auth extract``
    or ``auth set``).
    """

    resolve_app(app_name)

    # ── Step 1: load stored token and check for refresh_token ─────────
    token = load_token(app_name)
    if token is None or token.refresh_token is None:
        raise click.ClickException(
            f"No refresh token found for '{app_name}'. "
            "Run 'spectral auth extract' or 'spectral auth set' first to store one."
        )
    stored_refresh_token = token.refresh_token
    console.print(
        f"[bold]Using stored refresh token:[/bold] {stored_refresh_token[:20]}..."
    )

    # ── Step 2: load captures for LLM context ─────────────────────────
    bundle = load_app_bundle(app_name)

    init_debug(debug=debug)

    # ── Step 3: LLM generates refresh_token() ─────────────────────────
    conv = Conversation(
        system=[build_timeline(bundle), get_auth_rules()],
        max_tokens=8192,
        max_iterations=20,
        label="generate_auth_refresh",
        tool_names=["decode_base64", "decode_url", "decode_jwt", "query_traces"],
        bundle=bundle,
    )

    console.print("[bold]Generating refresh script...[/bold]")
    initial_text = conv.ask_text(get_refresh_instructions())
    validated = validate_function(
        conv,
        extract_refresh_script,
        initial_text=initial_text,
        fn="refresh_token",
        fn_args=(stored_refresh_token,),
    )
    if validated is None:
        console.print("[dim]No working refresh script produced.[/dim]")
        return
    script, refresh_result = validated

    # ── Step 4: save script and token ─────────────────────────────────
    script_path = refresh_script_path(app_name)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script)

    if isinstance(refresh_result, dict):
        save_auth_result(app_name, refresh_result)  # type: ignore[arg-type]
        console.print("[green]Token saved.[/green]")

    console.print(f"[green]Refresh script written to {script_path}[/green]")
