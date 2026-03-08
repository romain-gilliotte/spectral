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

from cli.commands.capture.types import CaptureBundle, Trace
from cli.helpers.console import console
import cli.helpers.llm as llm
from cli.helpers.prompt import render


class NoAuthDetected(Exception):
    """Raised when the LLM finds no authentication mechanism in the traces."""


_NO_AUTH_SENTINEL = "NO_AUTH"


def get_auth_instructions() -> str:
    """Return the rendered auth system prompt."""
    return render("auth-instructions.j2", no_auth_sentinel=_NO_AUTH_SENTINEL)


async def generate_auth_script(
    bundle: CaptureBundle,
    api_name: str,
    system_context: str | None = None,
) -> str:
    """Discover auth mechanism from traces and generate token functions.

    Returns Python source code containing ``acquire_token()`` and
    optionally ``refresh_token()`` (string).
    Raises NoAuthDetected if the LLM finds no auth.
    """
    trace_summaries = prepare_trace_list(bundle.traces)

    prompt = render(
        "auth-generate-script.j2",
        api_name=api_name,
        trace_summaries=trace_summaries,
    )

    system: list[str] | None = None
    if system_context is not None:
        system = [system_context, get_auth_instructions()]

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

    script = extract_script(text)
    validate_script(script)
    return script


def validate_script(script: str) -> None:
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


def prepare_trace_list(traces: list[Trace]) -> str:
    """Build a compact list of auth-related traces for the prompt."""
    auth_keywords = {
        "auth", "login", "token", "oauth", "session", "signin",
        "verification", "otp", "verify", "password", "credential",
        "callback", "refresh",
    }
    lines: list[str] = []
    for t in traces:
        url_lower = t.meta.request.url.lower()
        req_headers = {h.name.lower() for h in t.meta.request.headers}
        is_auth = (
            "authorization" in req_headers
            or any(kw in url_lower for kw in auth_keywords)
            or t.meta.response.status in (401, 403)
        )
        marker = " [AUTH]" if is_auth else ""
        lines.append(
            f"- {t.meta.id}: {t.meta.request.method} {t.meta.request.url} "
            f"→ {t.meta.response.status}{marker}"
        )
    return "\n".join(lines)


def extract_script(text: str) -> str:
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
@click.option("--model", default="claude-sonnet-4-5-20250929", help="LLM model to use")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def analyze(app_name: str, model: str, debug: bool) -> None:
    """Analyze auth mechanism for an app and generate an auth script."""
    from cli.helpers.context import build_shared_context
    from cli.helpers.detect_base_url import detect_base_url
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
    llm.set_model(model)

    async def _run() -> str:
        base_url = await detect_base_url(bundle, app_name)
        console.print(f"  API base URL: {base_url}")

        system_context = build_shared_context(bundle, base_url)

        script = await generate_auth_script(
            bundle=bundle,
            api_name=app_name,
            system_context=system_context,
        )

        return script

    try:
        script = asyncio.run(_run())
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
