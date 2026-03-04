"""Step: Generate MCP auth script (acquire_token / refresh_token)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cli.commands.analyze.steps.base import Step, StepValidationError
from cli.commands.analyze.steps.generate_auth_script import (
    _auth_summary,
    _execute_inspect_trace,
    _extract_script,
    _make_inspect_trace_tool,
    _prepare_trace_list,
)
from cli.commands.analyze.steps.types import AuthInfo
from cli.commands.analyze.tools import INVESTIGATION_TOOLS, TOOL_EXECUTORS
from cli.commands.capture.types import Trace
import cli.helpers.llm as llm
from cli.helpers.llm import compact_json


class GenerateMcpAuthScriptInput:
    """Input for MCP auth script generation."""

    def __init__(
        self, auth: AuthInfo, traces: list[Trace], api_name: str
    ) -> None:
        self.auth = auth
        self.traces = traces
        self.api_name = api_name


class GenerateMcpAuthScriptStep(Step[GenerateMcpAuthScriptInput, str]):
    """Generate MCP-style auth script with acquire_token() and refresh_token().

    Key differences from the base GenerateAuthScriptStep:
    - acquire_token() takes no args, prompts via injected prompt_text/prompt_secret
    - Returns {"headers": {...}, "refresh_token": "...", "expires_in": N}
    """

    name = "generate_mcp_auth_script"

    async def _execute(self, input: GenerateMcpAuthScriptInput) -> str:
        auth = input.auth
        traces = input.traces
        trace_summaries = _prepare_trace_list(traces)

        trace_index = {t.meta.id: t for t in traces}
        tools = INVESTIGATION_TOOLS + [_make_inspect_trace_tool()]
        executors: dict[str, Callable[[dict[str, Any]], str]] = {
            **TOOL_EXECUTORS,
            "inspect_trace": lambda inp: _execute_inspect_trace(
                inp, trace_index
            ),
        }

        prompt = f"""You are generating Python auth functions for the "{input.api_name}" MCP server.

## Context

You must produce ONLY two functions (the second is optional):

1. `acquire_token()` — **required**, takes NO arguments
2. `refresh_token(current_refresh_token)` — only if a refresh endpoint was detected

These functions are loaded dynamically by spectral. Two helper functions are injected into the module's namespace at load time:
- `prompt_text(label)` — prompt the user for text input (e.g., email, phone number)
- `prompt_secret(label)` — prompt the user for secret input with no echo (e.g., password, OTP code)

## Function contracts

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

## Auth analysis summary

{compact_json(_auth_summary(auth))}

## Available traces

Use the `inspect_trace` tool to examine any trace in detail.

{trace_summaries}

## Your task

1. First, use `inspect_trace` to examine the auth-related endpoints in detail
2. Then generate the function(s)

## Rules

- **Stdlib only**: only use `base64`, `json`, `re`, `time`, `urllib.parse`, `urllib.request` — zero pip dependencies
- **No caching**: do not cache tokens, do not read/write files
- **Use prompt helpers**: use `prompt_text("Email")` and `prompt_secret("Password")` for user input
- **Return headers**: return the actual HTTP headers to inject, not raw tokens
- **Include necessary imports** at the top of your code
- **Handle the FULL auth flow**: if auth requires multiple steps, acquire_token must handle ALL steps
- **Error handling**: raise clear exceptions on failure

## Output format

Respond with ONLY the Python code inside a ```python code block."""

        text = await llm.ask(
            prompt,
            max_tokens=8192,
            label="generate_mcp_auth_script",
            tools=tools,
            executors=executors,
        )

        return _extract_script(text)

    def _validate_output(self, output: str) -> None:
        try:
            compile(output, "<mcp-auth>", "exec")
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
