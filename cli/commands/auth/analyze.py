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


class NoAuthDetected(Exception):
    """Raised when the LLM finds no authentication mechanism in the traces."""


_NO_AUTH_SENTINEL = "NO_AUTH"

AUTH_INSTRUCTIONS = f"""\
You are generating Python auth functions for a web API.

## Your task

Survey the trace list below. Traces annotated with `[AUTH]` are likely auth-related (login endpoints, token exchanges, authenticated requests). Use the `inspect_trace` tool to examine them in detail. Identify the authentication mechanism (login endpoint, token format, refresh flow, credential fields). Then generate the functions.

If you find NO authentication mechanism (no login endpoint, no token exchange, no auth headers), respond with exactly: {_NO_AUTH_SENTINEL}

## Function contracts

You must produce ONLY two functions (the second is optional):

1. `acquire_token()` — **required**, takes NO arguments
2. `refresh_token(current_refresh_token)` — only if a refresh endpoint was detected

These functions are loaded dynamically by spectral. Helper functions are injected into the module's namespace at load time:
- `prompt_text(label)` — prompt the user for text input (e.g., email, phone number)
- `prompt_secret(label)` — prompt the user for secret input with no echo (e.g., password, OTP code)
- `tell_user(message)` — display a message to the user (e.g., "Open this URL in your browser: ...")
- `wait_user_confirmation(message)` — display a message and wait for the user to press Enter (e.g., for OAuth flows where the user must authorize in a browser before continuing)
- `debug(...)` — log intermediate values for troubleshooting (same interface as print). Output is captured and shown to you if the script fails, so you can diagnose issues. Use it freely for response bodies, status codes, token contents, etc.

### acquire_token()
- Takes NO arguments — use `prompt_text(label)` and `prompt_secret(label)` to get user credentials
- Must perform the FULL authentication flow (all steps: request OTP, then verify, etc.)
- Returns a dict with:
  - "headers": dict of HTTP headers to inject (e.g., {{"Authorization": "Bearer ey..."}})
  - "refresh_token": optional, for later use with refresh_token()
  - "expires_in": optional, token lifetime in seconds

### refresh_token(current_refresh_token) — optional
- Receives the current refresh token string
- Returns the same dict format as acquire_token
- Raises Exception on failure

## Rules

- **Stdlib only**: only use `base64`, `json`, `re`, `time`, `urllib.parse`, `urllib.request` — zero pip dependencies
- **No caching**: do not cache tokens, do not read/write files
- **Use injected helpers**: use `prompt_text`/`prompt_secret` for user input, `tell_user`/`wait_user_confirmation` for messages, `debug` for troubleshooting. Do NOT use `input()` or `print()` directly
- **Return headers**: return the actual HTTP headers to inject, not raw tokens
- **Include necessary imports** at the top of your code
- **Handle the FULL auth flow**: if auth requires multiple steps, acquire_token must handle ALL steps
- **Error handling**: raise clear exceptions on failure
- **Reproduce all request headers**: the captured traffic may come from a mobile app, browser, or other client. APIs often validate the client identity via custom headers (User-Agent, app version, device info, API keys, etc.) and reject requests missing them with 403. Copy ALL non-standard request headers from the captured traces into your HTTP requests. Only omit headers managed automatically by urllib (`Host`, `Content-Length`, `Accept-Encoding`)
- **Only use observed endpoints**: only call endpoints you can see in the captured traces. If a flow (e.g., token refresh) was not captured, make `refresh_token` raise an exception explaining the endpoint was not observed instead of guessing a URL

## Output format

Respond with ONLY the Python code inside a ```python code block. Or respond with {_NO_AUTH_SENTINEL} if no auth mechanism was found."""


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
    trace_summaries = _prepare_trace_list(bundle.traces)

    prompt = f"""## API: {api_name}

## Available traces

Use the `inspect_trace` tool to examine any trace in detail.

{trace_summaries}"""

    system: list[str] | None = None
    if system_context is not None:
        system = [system_context, AUTH_INSTRUCTIONS]

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


def _prepare_trace_list(traces: list[Trace]) -> str:
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


async def fix_auth_script(
    bundle: CaptureBundle,
    api_name: str,
    system_context: str | None,
    current_script: str,
    error_trace: str,
    conv: llm.Conversation | None = None,
) -> tuple[str, llm.Conversation]:
    """Fix a failing auth script using the LLM.

    Provides the LLM with the trace list, current script, and runtime error
    so it can generate a corrected version.

    If *conv* is provided, reuses the existing conversation (follow-up turn)
    so the LLM remembers previous fix attempts. Otherwise creates a new one.

    Returns ``(fixed_script, conversation)`` so the caller can pass the
    conversation back for subsequent fix attempts.
    """
    if conv is None:
        # First fix attempt: build the full prompt with trace list + script + error
        trace_summaries = _prepare_trace_list(bundle.traces)

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

    script = _extract_script(text)
    _validate_script(script)
    return script, conv


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
