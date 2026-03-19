"""CLI command: spectral auth login."""

from __future__ import annotations

import traceback

import click

from cli.helpers.auth.errors import (
    AuthScriptError,
    AuthScriptInvalid,
    AuthScriptNotFound,
)
from cli.helpers.auth.generation import extract_script, get_auth_instructions
from cli.helpers.auth.usage import acquire_auth
from cli.helpers.console import console
from cli.helpers.context import build_timeline
from cli.helpers.llm import Conversation, init_debug
from cli.helpers.prompt import render
from cli.helpers.storage import auth_script_path, load_app_bundle, resolve_app

_MAX_FIX_ATTEMPTS = 5


@click.command()
@click.argument("app_name")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def login(app_name: str, debug: bool) -> None:
    """Run interactive authentication for an app.

    Loads auth_acquire.py, calls acquire_token(), and writes token.json.
    If the script fails, offers to fix it with the LLM.
    """

    console.print(f"[bold]Logging in to {app_name}...[/bold]")

    resolve_app(app_name)
    init_debug(debug=debug)
    _attempt_login(app_name)


def _attempt_login(app_name: str) -> None:
    output: list[str] = []
    try:
        acquire_auth(app_name, output=output)
        console.print("[green]Login successful. Token saved.[/green]")

    except AuthScriptNotFound:
        raise click.ClickException(
            f"Auth script not found for '{app_name}'. "
            f"Run 'spectral auth analyze {app_name}' to generate one."
        )

    except AuthScriptError:
        console.print("[red]Login failed:[/red]")
        error_trace = traceback.format_exc()
        console.print(error_trace)

        if not click.confirm(
            "Would you like the LLM to fix the auth script?", default=True
        ):
            raise click.ClickException(
                f"Auth script failed for '{app_name}'. "
                f"Run 'spectral auth analyze {app_name}' to generate another one."
            )

        _attempt_fix_and_retry(app_name, error_trace, output)


def _attempt_fix_and_retry(app_name: str, error_trace: str, output: list[str]) -> None:
    bundle = load_app_bundle(app_name)
    conversation = Conversation(
        system=[build_timeline(bundle), get_auth_instructions()],
        max_tokens=8192,
        label="fix_auth_script",
        tool_names=["decode_base64", "decode_url", "decode_jwt", "inspect_trace"],
        bundle=bundle,
    )
    script_path = auth_script_path(app_name)

    for attempt in range(_MAX_FIX_ATTEMPTS):
        current_script = script_path.read_text()
        prompt = render(
            "auth-fix.j2",
            attempt=attempt,
            current_script=current_script,
            traceback=error_trace,
            script_stdout="".join(output),
        )
        text = conversation.ask_text(prompt)

        try:
            fixed_script = extract_script(text)
        except AuthScriptInvalid as e:
            console.print(f"[red]LLM produced invalid code:[/red] {e}")
            error_trace = str(e)
            output = []
            continue

        if fixed_script is None:
            raise click.ClickException(
                f"No auth mechanism found for '{app_name}'. "
                f"Run 'spectral auth analyze {app_name}' to regenerate."
            )

        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(fixed_script)
        console.print("[green]Script updated. Retrying login...[/green]")

        output = []
        try:
            acquire_auth(app_name, output=output)
            console.print("[green]Login successful. Token saved.[/green]")
            return
        except AuthScriptError:
            error_trace = traceback.format_exc()
            console.print("[red]Login still failing:[/red]")
            console.print(error_trace)

    console.print(
        f"[red]Exhausted {_MAX_FIX_ATTEMPTS} fix attempts. "
        f"The LLM was unable to produce a working auth script.[/red]"
    )
    raise click.ClickException(
        f"Run 'spectral auth analyze {app_name}' to regenerate from scratch."
    )
