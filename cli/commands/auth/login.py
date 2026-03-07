"""CLI command: spectral auth login."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import click

from cli.helpers.console import console

if TYPE_CHECKING:
    from cli.commands.capture.types import CaptureBundle
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
    import traceback

    from cli.helpers.auth_runtime import acquire_auth, captured_script_output
    from cli.helpers.storage import auth_script_path, resolve_app, write_token

    resolve_app(app_name)

    # Lazily initialized on first fix attempt
    bundle: CaptureBundle | None = None
    system_context: str | None = None
    fix_conv: Conversation | None = None  # reused across fix attempts

    while True:
        console.print(f"[bold]Logging in to {app_name}...[/bold]")
        try:
            token = acquire_auth(app_name)
        except Exception:
            traceback_str = traceback.format_exc()
            stdout_output = "".join(captured_script_output)
            if stdout_output:
                traceback_str = f"## Script stdout\n\n{stdout_output}\n## Traceback\n\n{traceback_str}"
            console.print("[red]Login failed:[/red]")
            console.print(traceback_str)

            if not click.confirm(
                "Would you like the LLM to fix the auth script?", default=True
            ):
                raise SystemExit(1)

            # Lazy init LLM, bundle, and system context on first fix
            if bundle is None:
                from cli.helpers.context import build_shared_context
                from cli.helpers.detect_base_url import detect_base_url
                import cli.helpers.llm as llm_mod
                from cli.helpers.storage import load_app_bundle

                llm_mod.init_debug(debug=debug)
                llm_mod.set_model(model)

                bundle = load_app_bundle(app_name)

                async def _detect_url() -> str:
                    return await detect_base_url(bundle, app_name)  # type: ignore[arg-type]

                base_url = asyncio.run(_detect_url())
                system_context = build_shared_context(bundle, base_url)

            script_path = auth_script_path(app_name)
            current_script = script_path.read_text()

            fixed_script, fix_conv = asyncio.run(
                fix_auth_script(
                    bundle=bundle,
                    api_name=app_name,
                    system_context=system_context,
                    current_script=current_script,
                    error_trace=traceback_str,
                    conv=fix_conv,
                )
            )

            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text(fixed_script)
            console.print("[green]Script updated. Retrying login...[/green]")
            continue

        write_token(app_name, token)
        console.print("[green]Login successful. Token saved.[/green]")
        break


async def fix_auth_script(
    bundle: CaptureBundle,
    api_name: str,
    system_context: str | None,
    current_script: str,
    error_trace: str,
    conv: Conversation | None = None,
) -> tuple[str, Conversation]:
    """Fix a failing auth script using the LLM.

    Provides the LLM with the trace list, current script, and runtime error
    so it can generate a corrected version.

    If *conv* is provided, reuses the existing conversation (follow-up turn)
    so the LLM remembers previous fix attempts. Otherwise creates a new one.

    Returns ``(fixed_script, conversation)`` so the caller can pass the
    conversation back for subsequent fix attempts.
    """
    from cli.commands.auth.analyze import (
        AUTH_INSTRUCTIONS,
        extract_script,
        prepare_trace_list,
        validate_script,
    )
    import cli.helpers.llm as llm

    if conv is None:
        # First fix attempt: build the full prompt with trace list + script + error
        trace_summaries = prepare_trace_list(bundle.traces)

        prompt = f"""## API: {api_name}

## Available traces

Use the `inspect_trace` tool to examine any trace in detail.

{trace_summaries}

## Current auth script (failing)

```python
{current_script}
```

## Runtime error

{error_trace}

Fix the script so it works. You may add `debug()` calls to log intermediate values (their output will be shown to you if the script fails again). Return ONLY the corrected Python code in a ```python block."""

        system: list[str] | None = None
        if system_context is not None:
            system = [system_context, AUTH_INSTRUCTIONS]

        conv = llm.Conversation(
            system=system,
            max_tokens=8192,
            label="fix_auth_script",
            tool_names=["decode_base64", "decode_url", "decode_jwt", "inspect_trace"],
            bundle=bundle,
        )
    else:
        # Follow-up fix attempt: send just the new error
        prompt = f"""The fixed script still fails. Here is the new error:

{error_trace}

Fix the script so it works. You may add `debug()` calls to log intermediate values (their output will be shown to you if the script fails again). Return ONLY the corrected Python code in a ```python block."""

    text = await conv.ask_text(prompt)

    script = extract_script(text)
    validate_script(script)
    return script, conv
