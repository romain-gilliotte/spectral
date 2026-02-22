"""Step: Generate token acquisition functions using LLM.

The LLM receives auth-related trace summaries and can inspect full
request/response bodies via tools.  It produces only the ``acquire_token``
(and optionally ``refresh_token``) functions — pure stdlib, no caching,
no Restish awareness.  The framework code is stitched on by the caller.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from cli.commands.analyze.steps.base import Step
from cli.commands.analyze.steps.types import AuthInfo
from cli.commands.analyze.tools import INVESTIGATION_TOOLS, TOOL_EXECUTORS
from cli.commands.analyze.utils import sanitize_headers, truncate_json
from cli.commands.capture.types import Trace
import cli.helpers.llm as llm
from cli.helpers.llm import compact_json


class GenerateAuthScriptInput:
    """Input for the auth script generation step."""

    def __init__(
        self, auth: AuthInfo, traces: list[Trace], api_name: str
    ) -> None:
        self.auth = auth
        self.traces = traces
        self.api_name = api_name


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
    return compact_json(result)


# -- The step ----------------------------------------------------------------


class GenerateAuthScriptStep(Step[GenerateAuthScriptInput, str]):
    """Generate token acquisition functions using LLM.

    Input: GenerateAuthScriptInput (AuthInfo + traces + api_name).
    Output: Python source code containing ``acquire_token()`` and
            optionally ``refresh_token()`` (string).
    """

    name = "generate_auth_script"

    async def _execute(self, input: GenerateAuthScriptInput) -> str:
        auth = input.auth
        traces = input.traces

        # Build auth-related trace summary for the prompt
        trace_summaries = _prepare_trace_list(traces)

        # Build tools: investigation tools + inspect_trace
        trace_index = _build_trace_index(traces)
        tools = INVESTIGATION_TOOLS + [_make_inspect_trace_tool()]
        executors: dict[str, Callable[[dict[str, Any]], str]] = {
            **TOOL_EXECUTORS,
            "inspect_trace": lambda inp: _execute_inspect_trace(
                inp, trace_index
            ),
        }

        prompt = f"""You are generating Python token acquisition functions for the "{input.api_name}" API.

## Context

You must produce ONLY two functions (the second is optional):

1. `acquire_token(credentials: dict[str, str]) -> dict[str, str]` — **required**
2. `refresh_token(current_refresh_token: str) -> dict[str, str]` — only if a refresh endpoint was detected

These functions will be embedded in a larger script that handles caching, expiry, user prompting, and Restish integration. You do NOT need to handle any of that.

## Function contracts

### acquire_token(credentials)
- Receives a dict with credential field values: {_credential_fields_hint(auth)}
- Must perform the FULL authentication flow (all steps: OTP request, then verify, etc.)
- Returns a dict with at minimum: {{"token": "the_access_token"}}
- May also include: "refresh_token", "expires_in" (seconds as string or int)
- Raises Exception on failure

### refresh_token(current_refresh_token) — optional
- Receives the current refresh token string
- Returns the same dict format as acquire_token
- Raises Exception on failure

## Auth analysis summary

{compact_json(_auth_summary(auth))}

## Available traces

Use the `inspect_trace` tool to examine any trace in detail (request/response bodies, headers).

{trace_summaries}

## Your task

1. First, use `inspect_trace` to examine the auth-related endpoints in detail. Understand the full authentication flow (all steps: OTP request, login, token extraction, etc.)
2. Then generate the function(s).

## Rules

- **Stdlib only**: only use `base64`, `json`, `re`, `time`, `urllib.parse`, `urllib.request` — zero pip dependencies
- **No caching**: do not cache tokens, do not read/write files
- **No user prompting**: credentials are passed as a parameter, do not use input() or getpass
- **No stdin/stdout interaction**: no Restish contract, no JSON piping
- **Include necessary imports** at the top of your code (before the function definitions)
- **Handle the FULL auth flow**: if auth requires multiple steps (e.g., request OTP then verify), acquire_token must handle ALL steps
- For mid-flow interactive prompts (e.g., OTP code the user must enter), you MAY read from `/dev/tty` as a special case
- **Error handling**: raise clear exceptions on failure

## Output format

Respond with ONLY the Python code inside a ```python code block. No explanation before or after."""

        text = await llm.ask(
            prompt,
            max_tokens=8192,
            label="generate_auth_script",
            tools=tools,
            executors=executors,
        )

        return _extract_script(text)

    def _validate_output(self, output: str) -> None:
        # Must compile as valid Python
        try:
            compile(output, "<auth-acquire>", "exec")
        except SyntaxError as e:
            from cli.commands.analyze.steps.base import StepValidationError

            raise StepValidationError(
                f"Generated script has syntax error: {e}",
                {"error": str(e)},
            )

        # Must define acquire_token
        if "def acquire_token" not in output:
            from cli.commands.analyze.steps.base import StepValidationError

            raise StepValidationError(
                "Generated code must define an acquire_token() function",
                {"error": "missing acquire_token"},
            )


def _credential_fields_hint(auth: AuthInfo) -> str:
    """Build a hint about expected credential field keys for the prompt."""
    if auth.login_config and auth.login_config.credential_fields:
        fields = auth.login_config.credential_fields
        return ", ".join(f'"{k}": "{v}"' for k, v in fields.items())
    return '"username": "...", "password": "..."'


def _auth_summary(auth: AuthInfo) -> dict[str, Any]:
    """Convert AuthInfo to a dict for the LLM prompt."""
    result: dict[str, Any] = {
        "type": auth.type,
        "obtain_flow": auth.obtain_flow,
        "token_header": auth.token_header,
        "token_prefix": auth.token_prefix,
    }
    if auth.business_process:
        result["business_process"] = auth.business_process
    if auth.user_journey:
        result["user_journey"] = auth.user_journey
    if auth.discovery_notes:
        result["discovery_notes"] = auth.discovery_notes
    if auth.login_config:
        lc = auth.login_config
        result["login_endpoint"] = {
            "url": lc.url,
            "method": lc.method,
            "credential_fields": lc.credential_fields,
            "extra_fields": lc.extra_fields,
        }
    if auth.refresh_config:
        rc = auth.refresh_config
        result["refresh_endpoint"] = {
            "url": rc.url,
            "method": rc.method,
            "token_field": rc.token_field,
        }
    return result


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
