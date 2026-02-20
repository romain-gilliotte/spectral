"""Step: Generate a self-contained auth helper script using LLM.

The LLM receives auth-related trace summaries and can inspect full
request/response bodies via tools.  It produces a Python script that
follows the Restish external-tool contract (JSON on stdin/stdout).
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from cli.commands.analyze.steps.base import LLMStep
from cli.commands.analyze.steps.types import AuthInfo
from cli.commands.analyze.tools import INVESTIGATION_TOOLS, TOOL_EXECUTORS
from cli.commands.analyze.utils import sanitize_headers, truncate_json
from cli.commands.capture.types import Trace
import cli.helpers.llm as llm


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
    return json.dumps(result, indent=2)


# -- The step ----------------------------------------------------------------


class GenerateAuthScriptStep(LLMStep[GenerateAuthScriptInput, str]):
    """Generate a self-contained Python auth helper script using LLM.

    Input: GenerateAuthScriptInput (AuthInfo + traces + api_name).
    Output: Complete Python script source code (string).
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

        prompt = f"""You are generating a self-contained Python auth helper script for the "{input.api_name}" API.

## Context

This script is called by Restish (a CLI tool) via the "external-tool" auth mechanism:
- Restish pipes a JSON request to stdin: {{"method": "GET", "uri": "/some/path", "headers": {{}}, "body": ""}}
- The script must add authentication headers and write the modified JSON to stdout
- The script must handle token caching so the user isn't prompted on every request

## Auth analysis summary

{json.dumps(_auth_summary(auth), indent=2)}

## Available traces

Use the `inspect_trace` tool to examine any trace in detail (request/response bodies, headers).

{trace_summaries}

## Your task

1. First, use `inspect_trace` to examine the auth-related endpoints in detail. Understand the full authentication flow (all steps: OTP request, login, token extraction, etc.)
2. Then generate a complete Python script that replicates this auth flow.

## Script requirements

- **Shebang**: `#!/usr/bin/env python3`
- **Stdlib only**: only use `base64`, `getpass`, `json`, `re`, `sys`, `time`, `urllib.parse`, `urllib.request`, `pathlib` — zero pip dependencies
- **Token caching**: cache tokens in `~/.cache/spectral/{input.api_name}/token.json`. Include `acquired_at` timestamp. Check JWT `exp` claim if present, else use 1h TTL.
- **Restish contract**: read JSON from stdin, add auth to `headers` dict, write JSON to stdout. IMPORTANT: Restish expects header values as arrays of strings, not plain strings. Example: `request["headers"]["Authorization"] = ["Bearer " + token]` (note the list wrapper).
- **Interactive prompts**: since stdin is consumed by the Restish JSON request and stderr may be captured by Restish, you MUST both write prompts AND read input from `/dev/tty`. Open `/dev/tty` in write mode for prompts, and in read mode for reading user input. Do NOT use `input()` or `sys.stdin`. For passwords/secrets, use `getpass.getpass(prompt, stream=open('/dev/tty', 'w'))` (getpass already reads from /dev/tty by default). Debug/error messages should also go to `/dev/tty` so the user can see them.
- **Handle the FULL auth flow**: if auth requires multiple steps (e.g., request OTP, then verify), the script must handle ALL steps.
- **Token refresh**: if a refresh mechanism was detected, implement it.
- **Error handling**: print clear error messages to stderr on failure.

## Output format

Respond with ONLY the Python script inside a ```python code block. No explanation before or after."""

        text = await llm.ask(
            prompt,
            model=self.model,
            max_tokens=8192,
            label="generate_auth_script",
            tools=tools,
            executors=executors,
        )

        return _extract_script(text)

    def _validate_output(self, output: str) -> None:
        # Must compile as valid Python
        try:
            compile(output, "<auth-helper>", "exec")
        except SyntaxError as e:
            from cli.commands.analyze.steps.base import StepValidationError

            raise StepValidationError(
                f"Generated script has syntax error: {e}",
                {"error": str(e)},
            )


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
    # Fallback: if the response starts with a shebang, take it as-is
    if text.strip().startswith("#!/"):
        return text.strip() + "\n"
    raise ValueError("Could not extract Python script from LLM response")
