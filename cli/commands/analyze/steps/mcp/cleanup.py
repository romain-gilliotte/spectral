"""Step: Remove traces matching a built tool's template."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from cli.commands.analyze.steps.base import Step
from cli.commands.analyze.steps.mcp.types import CleanupInput
from cli.commands.analyze.utils import pattern_to_regex
from cli.commands.capture.types import Trace


class CleanupTracesStep(Step[CleanupInput, list[Trace]]):
    """Remove traces from the pool that match the built tool's request template.

    Match criteria: same method, URL path matches the path pattern,
    and fixed body values match. This is the generalization mechanism.
    """

    name = "cleanup_traces"

    async def _execute(self, input: CleanupInput) -> list[Trace]:
        tool = input.tool_definition
        req = tool.request
        base_url = input.base_url.rstrip("/")

        # Build path regex
        full_pattern = base_url + req.path
        parsed_pattern = urlparse(full_pattern)
        path_regex = pattern_to_regex(parsed_pattern.path)

        # Collect fixed body values (non-$param entries)
        fixed_body = _extract_fixed_values(req.body) if req.body else {}

        remaining: list[Trace] = []
        for trace in input.traces:
            if _trace_matches(trace, req.method, path_regex, fixed_body):
                continue  # Remove this trace
            remaining.append(trace)

        return remaining


def _trace_matches(
    trace: Trace,
    method: str,
    path_regex: re.Pattern[str],
    fixed_body: dict[str, Any],
) -> bool:
    """Check if a trace matches the tool template."""
    # Method must match
    if trace.meta.request.method.upper() != method.upper():
        return False

    # URL path must match the pattern
    parsed_url = urlparse(trace.meta.request.url)
    if not path_regex.match(parsed_url.path):
        return False

    # If there are fixed body values, check they match
    if fixed_body and trace.request_body:
        try:
            body = json.loads(trace.request_body)
            if isinstance(body, dict):
                for key, expected in fixed_body.items():
                    if key in body and body[key] != expected:
                        return False
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    return True


def _extract_fixed_values(obj: dict[str, Any] | None) -> dict[str, Any]:
    """Extract non-$param values from a body template (top-level only)."""
    if obj is None:
        return {}
    fixed: dict[str, Any] = {}
    for key, value in obj.items():
        if isinstance(value, dict) and "$param" in value:
            continue
        if isinstance(value, (str, int, float, bool)):
            fixed[key] = value
    return fixed
