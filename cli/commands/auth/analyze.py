"""Generate and validate token acquisition functions using LLM.

The LLM receives trace summaries, discovers the auth mechanism itself,
and generates ``acquire_token()`` / ``refresh_token()`` functions.
The generated script is then tested interactively: ``acquire_token()`` is
called (prompting the user for credentials), and if it fails the error is
fed back to the LLM on the same conversation for correction.  The same
validation loop runs for ``refresh_token()`` when present.

Raises ``NoAuthDetected`` if the LLM concludes there is no auth.

Also contains the ``spectral auth analyze`` Click command.
"""

from __future__ import annotations

import click

from cli.helpers.auth import (
    AuthScriptError,
    AuthScriptInvalid,
    call_auth_module_source,
    extract_script,
    get_auth_instructions,
    save_auth_result,
    script_has_refresh,
)
from cli.helpers.console import console
from cli.helpers.context import build_timeline
from cli.helpers.llm import Conversation, init_debug
from cli.helpers.prompt import render
from cli.helpers.storage import auth_script_path, load_app_bundle, resolve_app

_MAX_FIX_ATTEMPTS = 10


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
        max_iterations=20,
        label="generate_auth_script",
        tool_names=["decode_base64", "decode_url", "decode_jwt", "query_traces"],
        bundle=bundle,
    )

    # ── Step 1+2: generate, validate, and fix acquire_token ─────────────
    console.print("[bold]Generating auth script...[/bold]")
    initial_text = conv.ask_text(get_auth_instructions())
    validated = _validate_function(conv, initial_text=initial_text, fn="acquire_token")
    if validated is None:
        console.print("[dim]No working auth script produced.[/dim]")
        return
    script, acquire_result = validated

    # Save the working script (acquire confirmed OK)
    script_path = auth_script_path(app_name)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script)

    # Track the last successful auth result for token persistence
    last_result = acquire_result

    # ── Step 3: validate refresh_token if present ───────────────────────
    if script_has_refresh(script):
        console.print("[bold]Testing refresh_token()...[/bold]")
        result: dict[str, object] = acquire_result  # type: ignore[assignment]
        refresh_token = (
            str(result["refresh_token"]) if result.get("refresh_token") else None
        )

        if refresh_token is None:
            console.print(
                "[dim]acquire_token() did not return a refresh_token. "
                "Skipping refresh validation.[/dim]"
            )
        else:
            validated = _validate_function(
                conv,
                script,
                fn="refresh_token",
                fn_args=(refresh_token,),
            )
            if validated is not None:
                script = validated[0]
                last_result = validated[1]
                script_path.write_text(script)
    else:
        console.print(
            "[dim]No refresh_token() in script — skipping refresh validation.[/dim]"
        )

    # Persist the token so `spectral auth login` is not needed
    if isinstance(last_result, dict):
        save_auth_result(app_name, last_result)  # type: ignore[arg-type]
        console.print("[green]Token saved.[/green]")

    console.print(f"[green]Auth script written to {script_path}[/green]")


# ── Shared fix loop ────────────────────────────────────────────────────────


def _validate_function(
    conv: Conversation,
    script: str | None = None,
    *,
    initial_text: str | None = None,
    fn: str,
    fn_args: tuple[object, ...] = (),
) -> tuple[str, object] | None:
    """Extract, run, and fix *fn* in a single loop.

    Either *script* (already extracted) or *initial_text* (raw LLM output
    to extract from) must be provided.  Returns ``(script, result)`` on
    success, or ``None`` if all attempts were exhausted or NO_AUTH.
    """

    prompt_cache: dict[str, str] = {}
    # Text waiting to be extracted — set on first iteration or after a fix
    pending_text = initial_text

    for attempt in range(_MAX_FIX_ATTEMPTS):
        # ── Extract script from LLM text if needed ──────────────────
        if pending_text is not None:
            try:
                script = extract_script(pending_text)
            except AuthScriptInvalid as e:
                console.print(
                    f"[yellow]Invalid script (attempt {attempt + 1}/{_MAX_FIX_ATTEMPTS}):[/yellow] {e}"
                )
                console.print("[dim]Asking the LLM to fix...[/dim]")
                pending_text = conv.ask_text(
                    render("auth-fix.j2", exception=e, script_stdout="")
                )
                continue
            pending_text = None

            if script is None:
                console.print(
                    "[dim]No authentication mechanism detected in traces. "
                    "No script generated.[/dim]"
                )
                return None

            console.print(f"[bold]Script generated. Testing {fn}()...[/bold]")

        assert script is not None

        # ── Test the script ─────────────────────────────────────────
        output: list[str] = []
        try:
            fn_result = call_auth_module_source(
                script, fn, output, *fn_args, prompt_cache=prompt_cache
            )
            console.print(f"[green]{fn}() succeeded.[/green]")
            return script, fn_result
        except AuthScriptError as e:
            cause = e.__cause__ or e
            console.print(
                f"[yellow]{fn}() failed (attempt {attempt + 1}/{_MAX_FIX_ATTEMPTS}):[/yellow] "
                f"{cause}"
            )
            console.print("[dim]Asking the LLM to fix the script...[/dim]")

        pending_text = conv.ask_text(
            render(
                "auth-fix.j2",
                exception=cause,
                script_stdout="".join(output),
            )
        )

    console.print(
        f"[red]Exhausted {_MAX_FIX_ATTEMPTS} fix attempts for {fn}(). "
        f"The LLM was unable to produce a working script.[/red]"
    )
    return None
