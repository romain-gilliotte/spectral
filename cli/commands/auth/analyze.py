"""Generate token acquisition functions using LLM.

The LLM receives trace summaries, discovers the auth mechanism itself,
and generates ``acquire_token()`` / ``refresh_token()`` functions.
Raises ``NoAuthDetected`` if the LLM concludes there is no auth.

Also contains the ``spectral auth analyze`` Click command.
"""

from __future__ import annotations

import asyncio
import re

import click

from cli.commands.capture.types import CaptureBundle
from cli.helpers.console import console
import cli.helpers.llm as llm
from cli.helpers.prompt import render


class NoAuthDetected(Exception):
    """Raised when the LLM finds no authentication mechanism in the traces."""


_NO_AUTH_SENTINEL = "NO_AUTH"


def _get_auth_instructions() -> str:
    """Return the rendered auth system prompt."""
    return render("auth-instructions.j2", no_auth_sentinel=_NO_AUTH_SENTINEL)


async def _generate_auth_script(
    bundle: CaptureBundle,
    api_name: str,
    system_context: str | None = None,
) -> str:
    """Discover auth mechanism from traces and generate token functions.

    Returns Python source code containing ``acquire_token()`` and
    optionally ``refresh_token()`` (string).
    Raises NoAuthDetected if the LLM finds no auth.
    """
    prompt = render(
        "auth-generate-script.j2",
        api_name=api_name,
        traces=bundle.traces,
    )

    system: list[str] | None = None
    if system_context is not None:
        system = [system_context, _get_auth_instructions()]

    conv = llm.Conversation(
        system=system,
        max_tokens=8192,
        label="generate_auth_script",
        tool_names=["decode_base64", "decode_url", "decode_jwt", "inspect_trace"],
        bundle=bundle,
    )
    text = await conv.ask_text(prompt)

    if _NO_AUTH_SENTINEL in text and "```" not in text:
        raise NoAuthDetected("LLM found no authentication mechanism")

    script = _extract_script(text)
    _validate_script(script)
    return script


def _validate_script(script: str) -> None:
    try:
        compile(script, "<auth-acquire>", "exec")
    except SyntaxError as e:
        raise ValueError(
            f"Generated script has syntax error: {e}",
        )

    if "def acquire_token" not in script:
        raise ValueError(
            "Generated code must define an acquire_token() function",
        )


def _extract_script(text: str) -> str:
    """Extract Python code from a markdown code block."""
    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip() + "\n"
    # Fallback: if the response starts with an import or def, take it as-is
    stripped = text.strip()
    if stripped.startswith(("import ", "from ", "def ")):
        return stripped + "\n"
    raise ValueError("Could not extract Python code from LLM response")


@click.command()
@click.argument("app_name")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def analyze(app_name: str, debug: bool) -> None:
    """Analyze auth mechanism for an app and generate an auth script."""
    from cli.helpers.storage import (
        auth_script_path,
        load_app_bundle,
        resolve_app,
    )

    resolve_app(app_name)
    console.print(f"[bold]Loading captures for app:[/bold] {app_name}")
    bundle = load_app_bundle(app_name)
    console.print(f"  Loaded {len(bundle.traces)} traces")

    llm.init_debug(debug=debug)

    try:
        script = asyncio.run(_run_auth(bundle, app_name))
    except NoAuthDetected:
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


async def _run_auth(bundle: CaptureBundle, app_name: str) -> str:
    from cli.helpers.context import build_shared_context
    from cli.helpers.detect_base_url import detect_base_url

    base_url = await detect_base_url(bundle, app_name)
    console.print(f"  API base URL: {base_url}")

    system_context = build_shared_context(bundle, base_url)

    script = await _generate_auth_script(
        bundle=bundle,
        api_name=app_name,
        system_context=system_context,
    )

    return script
