"""Generate token acquisition functions using LLM.

The LLM receives trace summaries, discovers the auth mechanism itself,
and generates ``acquire_token()`` / ``refresh_token()`` functions.
Raises ``NoAuthDetected`` if the LLM concludes there is no auth.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cli.commands.capture.types import Trace
from cli.commands.mcp.investigation import (
    execute_inspect_trace,
    make_inspect_trace_tool,
)
import cli.helpers.llm as llm
from cli.helpers.llm_tools import INVESTIGATION_TOOLS, TOOL_EXECUTORS


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

These functions are loaded dynamically by spectral. Two helper functions are injected into the module's namespace at load time:
- `prompt_text(label)` — prompt the user for text input (e.g., email, phone number)
- `prompt_secret(label)` — prompt the user for secret input with no echo (e.g., password, OTP code)

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
- **Use prompt helpers**: use `prompt_text("Email")` and `prompt_secret("Password")` for user input
- **Return headers**: return the actual HTTP headers to inject, not raw tokens
- **Include necessary imports** at the top of your code
- **Handle the FULL auth flow**: if auth requires multiple steps, acquire_token must handle ALL steps
- **Error handling**: raise clear exceptions on failure
- **Reproduce all request headers**: the captured traffic may come from a mobile app, browser, or other client. APIs often validate the client identity via custom headers (User-Agent, app version, device info, API keys, etc.) and reject requests missing them with 403. Copy ALL non-standard request headers from the captured traces into your HTTP requests. Only omit headers managed automatically by urllib (`Host`, `Content-Length`, `Accept-Encoding`)
- **Only use observed endpoints**: only call endpoints you can see in the captured traces. If a flow (e.g., token refresh) was not captured, make `refresh_token` raise an exception explaining the endpoint was not observed instead of guessing a URL

## Output format

Respond with ONLY the Python code inside a ```python code block. Or respond with {_NO_AUTH_SENTINEL} if no auth mechanism was found."""


async def generate_auth_script(
    traces: list[Trace],
    api_name: str,
    system_context: str | None = None,
) -> str:
    """Discover auth mechanism from traces and generate token functions.

    Returns Python source code containing ``acquire_token()`` and
    optionally ``refresh_token()`` (string).
    Raises NoAuthDetected if the LLM finds no auth.
    """
    trace_summaries = _prepare_trace_list(traces)

    trace_index = {t.meta.id: t for t in traces}
    tools = INVESTIGATION_TOOLS + [make_inspect_trace_tool()]
    executors: dict[str, Callable[[dict[str, Any]], str]] = {
        **TOOL_EXECUTORS,
        "inspect_trace": lambda inp: execute_inspect_trace(
            inp, trace_index
        ),
    }

    prompt = f"""## API: {api_name}

## Available traces

Use the `inspect_trace` tool to examine any trace in detail.

{trace_summaries}"""

    system: list[str] | None = None
    if system_context is not None:
        system = [system_context, AUTH_INSTRUCTIONS]

    text = await llm.ask(
        prompt,
        system=system,
        max_tokens=8192,
        label="generate_auth_script",
        tools=tools,
        executors=executors,
    )

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


def _extract_script(text: str) -> str:
    """Extract Python code from a markdown code block."""
    import re

    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip() + "\n"
    # Fallback: if the response starts with an import or def, take it as-is
    stripped = text.strip()
    if stripped.startswith(("import ", "from ", "def ")):
        return stripped + "\n"
    raise ValueError("Could not extract Python code from LLM response")
