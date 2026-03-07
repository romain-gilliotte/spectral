"""CLI command: spectral auth login."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import click

from cli.helpers.console import console

if TYPE_CHECKING:
    from cli.commands.capture.types import CaptureBundle
    from cli.formats.mcp_tool import TokenState
    from cli.helpers.llm import Conversation


@click.command()
@click.argument("app_name")
@click.option("--model", default="claude-sonnet-4-5-20250929", help="LLM model to use")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def login(app_name: str, model: str, debug: bool) -> None:
    """Run interactive authentication for an app.

    Loads auth_acquire.py, calls acquire_token(), and writes token.json.
    If the script fails, offers to fix it with the LLM.
    """
    from cli.helpers.auth_runtime import acquire_auth
    from cli.helpers.storage import resolve_app, write_token

    resolve_app(app_name)

    console.print(f"[bold]Logging in to {app_name}...[/bold]")
    try:
        token = acquire_auth(app_name)
    except Exception:
        error_str = _format_error()
        console.print("[red]Login failed:[/red]")
        console.print(error_str)

        if not click.confirm(
            "Would you like the LLM to fix the auth script?", default=True
        ):
            raise SystemExit(1)

        token = _fix_loop(app_name, model, debug, error_str)

    write_token(app_name, token)
    console.print("[green]Login successful. Token saved.[/green]")


def _format_error() -> str:
    """Format the current exception + captured script output into an error string."""
    import traceback

    from cli.helpers.auth_runtime import captured_script_output

    traceback_str = traceback.format_exc()
    stdout_output = "".join(captured_script_output)
    if stdout_output:
        traceback_str = f"## Script stdout\n\n{stdout_output}\n## Traceback\n\n{traceback_str}"
    return traceback_str


def _fix_loop(
    app_name: str, model: str, debug: bool, initial_error: str
) -> TokenState:
    """Initialize LLM context once, then loop: fix script → retry login."""
    from cli.helpers.auth_runtime import acquire_auth
    from cli.helpers.context import build_shared_context
    from cli.helpers.detect_base_url import detect_base_url
    import cli.helpers.llm as llm_mod
    from cli.helpers.storage import auth_script_path, load_app_bundle

    llm_mod.init_debug(debug=debug)
    llm_mod.set_model(model)

    bundle = load_app_bundle(app_name)

    async def _detect_url() -> str:
        return await detect_base_url(bundle, app_name)

    base_url = asyncio.run(_detect_url())
    system_context = build_shared_context(bundle, base_url)

    conv = _create_fix_conversation(bundle, system_context)

    script_path = auth_script_path(app_name)
    current_script = script_path.read_text()

    # First fix attempt
    fixed_script = asyncio.run(
        _request_fix(conv, bundle, app_name, current_script, initial_error, is_first=True)
    )

    while True:
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(fixed_script)
        console.print("[green]Script updated. Retrying login...[/green]")

        console.print(f"[bold]Logging in to {app_name}...[/bold]")
        try:
            return acquire_auth(app_name)
        except Exception:
            error_str = _format_error()
            console.print("[red]Login failed:[/red]")
            console.print(error_str)

            fixed_script = asyncio.run(
                _request_fix(conv, bundle, app_name, fixed_script, error_str, is_first=False)
            )


def _create_fix_conversation(
    bundle: CaptureBundle, system_context: str
) -> Conversation:
    """Create the LLM conversation for auth script fixing."""
    from cli.commands.auth.analyze import get_auth_instructions
    import cli.helpers.llm as llm_mod

    return llm_mod.Conversation(
        system=[system_context, get_auth_instructions()],
        max_tokens=8192,
        label="fix_auth_script",
        tool_names=["decode_base64", "decode_url", "decode_jwt", "inspect_trace"],
        bundle=bundle,
    )


async def _request_fix(
    conv: Conversation,
    bundle: CaptureBundle,
    api_name: str,
    current_script: str,
    error_trace: str,
    *,
    is_first: bool,
) -> str:
    """Send a fix prompt to the conversation and return the fixed script."""
    from cli.commands.auth.analyze import (
        extract_script,
        prepare_trace_list,
        validate_script,
    )
    from cli.helpers.prompt import render

    if is_first:
        trace_summaries = prepare_trace_list(bundle.traces)
        prompt = render(
            "auth-fix-initial.j2",
            api_name=api_name,
            trace_summaries=trace_summaries,
            current_script=current_script,
            error_trace=error_trace,
        )
    else:
        prompt = render("auth-fix-followup.j2", error_trace=error_trace)

    text = await conv.ask_text(prompt)
    script = extract_script(text)
    validate_script(script)
    return script
