"""Step: Generate token acquisition functions using LLM.

The LLM receives trace summaries, discovers the auth mechanism itself,
and generates ``acquire_token()`` / ``refresh_token()`` functions.
Raises ``NoAuthDetected`` if the LLM concludes there is no auth.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from cli.commands.analyze.steps.base import Step, StepValidationError
from cli.commands.analyze.tools import INVESTIGATION_TOOLS, TOOL_EXECUTORS
from cli.commands.analyze.utils import sanitize_headers, truncate_json
from cli.commands.capture.types import Trace
import cli.helpers.llm as llm
from cli.helpers.llm import compact_json


class NoAuthDetected(Exception):
    """Raised when the LLM finds no authentication mechanism in the traces."""


class GenerateAuthScriptInput:
    """Input for the auth script generation step."""

    def __init__(
        self,
        traces: list[Trace],
        api_name: str,
        system_context: str | None = None,
    ) -> None:
        self.traces = traces
        self.api_name = api_name
        self.system_context = system_context


# -- Tools: let the LLM inspect trace bodies --------------------------------

def _build_trace_index(traces: list[Trace]) -> dict[str, Trace]:
    return {t.meta.id: t for t in traces}


def _make_inspect_trace_tool() -> dict[str, Any]:
    return {
        "name": "inspect_trace",
        "description": (
            "Get the full request and response details for a specific trace, "
            "including headers and decoded body content (JSON or text). "
            "Use this to examine login endpoints, token responses, OTP flows, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trace_id": {
                    "type": "string",
                    "description": "The trace ID (e.g., 't_0001').",
                },
            },
            "required": ["trace_id"],
        },
    }


def _execute_inspect_trace(
    inp: dict[str, Any], index: dict[str, Trace]
) -> str:
    trace = index.get(inp["trace_id"])
    if trace is None:
        return f"Trace {inp['trace_id']} not found"

    result: dict[str, Any] = {
        "method": trace.meta.request.method,
        "url": trace.meta.request.url,
        "status": trace.meta.response.status,
        "request_headers": sanitize_headers(
            {h.name: h.value for h in trace.meta.request.headers}
        ),
        "response_headers": sanitize_headers(
            {h.name: h.value for h in trace.meta.response.headers}
        ),
    }
    if trace.request_body:
        try:
            result["request_body"] = truncate_json(
                json.loads(trace.request_body), max_keys=30
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            result["request_body_raw"] = trace.request_body.decode(
                errors="replace"
            )[:2000]
    if trace.response_body:
        try:
            result["response_body"] = truncate_json(
                json.loads(trace.response_body), max_keys=30
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            result["response_body_raw"] = trace.response_body.decode(
                errors="replace"
            )[:2000]
    serialized = compact_json(result)
    if len(serialized) > 4000:
        # Re-truncate with tighter limits to stay under budget
        if trace.response_body:
            try:
                result["response_body"] = truncate_json(
                    json.loads(trace.response_body), max_keys=10, max_depth=2
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        serialized = compact_json(result)
    return serialized


# -- The step ----------------------------------------------------------------


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


class GenerateAuthScriptStep(Step[GenerateAuthScriptInput, str]):
    """Discover auth mechanism from traces and generate token functions.

    Input: GenerateAuthScriptInput (traces + api_name + optional system_context).
    Output: Python source code containing ``acquire_token()`` and
            optionally ``refresh_token()`` (string).
    Raises NoAuthDetected if the LLM finds no auth.
    """

    name = "generate_auth_script"

    async def _execute(self, input: GenerateAuthScriptInput) -> str:
        traces = input.traces

        trace_summaries = _prepare_trace_list(traces)

        trace_index = _build_trace_index(traces)
        tools = INVESTIGATION_TOOLS + [_make_inspect_trace_tool()]
        executors: dict[str, Callable[[dict[str, Any]], str]] = {
            **TOOL_EXECUTORS,
            "inspect_trace": lambda inp: _execute_inspect_trace(
                inp, trace_index
            ),
        }

        prompt = f"""## API: {input.api_name}

## Available traces

Use the `inspect_trace` tool to examine any trace in detail.

{trace_summaries}"""

        system: list[str] | None = None
        if input.system_context is not None:
            system = [input.system_context, AUTH_INSTRUCTIONS]

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

        return _extract_script(text)

    def _validate_output(self, output: str) -> None:
        try:
            compile(output, "<auth-acquire>", "exec")
        except SyntaxError as e:
            raise StepValidationError(
                f"Generated script has syntax error: {e}",
                {"error": str(e)},
            )

        if "def acquire_token" not in output:
            raise StepValidationError(
                "Generated code must define an acquire_token() function",
                {"error": "missing acquire_token"},
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
