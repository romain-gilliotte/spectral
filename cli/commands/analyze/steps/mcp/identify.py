"""Step: Identify all business capabilities from traces in a single batch call."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import urlparse

from cli.commands.analyze.steps.base import Step
from cli.commands.analyze.steps.mcp.types import IdentifyInput, ToolCandidate
from cli.commands.analyze.utils import compact_url
from cli.commands.capture.types import Trace
from cli.helpers.http import get_header
import cli.helpers.llm as llm


class IdentifyCapabilitiesStep(Step[IdentifyInput, list[ToolCandidate]]):
    """Identify all business capabilities from the trace pool in one call.

    Returns a list of ToolCandidate (may be empty if nothing useful).
    """

    name = "identify_capabilities"

    async def _execute(self, input: IdentifyInput) -> list[ToolCandidate]:
        base_url = input.base_url
        parsed_base = urlparse(base_url)
        base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
        base_path = parsed_base.path.rstrip("/")

        # Build compact correlation summaries with enriched trace lines
        correlation_summaries: list[str] = []
        remaining_ids = {t.meta.id for t in input.remaining_traces}

        for corr in input.correlations:
            relevant_traces = [t for t in corr.traces if t.meta.id in remaining_ids]
            if not relevant_traces:
                continue

            ctx = corr.context
            action_desc = (
                f"[{ctx.meta.action}] "
                f"{ctx.meta.element.text or ctx.meta.element.selector} "
                f"on {ctx.meta.page.url}"
            )
            trace_lines = [
                _trace_summary_line(t, base_origin, base_path)
                for t in relevant_traces
            ]
            correlation_summaries.append(
                f"UI action: {action_desc}\nTriggered:\n" + "\n".join(trace_lines)
            )

        # Also list uncorrelated traces
        correlated_ids: set[str] = set()
        for corr in input.correlations:
            for t in corr.traces:
                correlated_ids.add(t.meta.id)
        uncorrelated = [
            t for t in input.remaining_traces if t.meta.id not in correlated_ids
        ]
        if uncorrelated:
            lines = [
                _trace_summary_line(t, base_origin, base_path)
                for t in uncorrelated
            ]
            correlation_summaries.append(
                "Uncorrelated traces (no UI action):\n" + "\n".join(lines)
            )

        prompt = f"""You are analyzing captured HTTP traffic to identify business capabilities that can become MCP tools.

Each tool represents one thing a user can do with the API (search, create, view, update, delete, etc.).

## Traces

{chr(10).join(correlation_summaries) if correlation_summaries else "No traces."}

## Your task

List ALL business capabilities you can identify from these traces. Return a JSON array.
- Ignore static assets, config files, analytics, tracking, and translation endpoints.
- Each capability should map to one API operation (one or more traces with the same endpoint).
- Use snake_case for tool names (e.g., search_routes, get_account).

If nothing useful exists, return an empty array: []

Otherwise return a JSON array of objects:
[{{"name": "tool_name", "description": "What this tool does in business terms", "trace_ids": ["t_0001", "t_0002"]}}]"""

        text = await llm.ask(
            prompt,
            label="identify_capabilities",
            max_tokens=4096,
        )

        data = llm.extract_json(text)

        if isinstance(data, list):
            return _parse_candidates(data)

        # Handle single-object response (LLM may return one instead of array)
        if data.get("stop"):
            return []
        return _parse_candidates([data])


def _trace_summary_line(
    trace: Trace, base_origin: str, base_path: str
) -> str:
    """Build an enriched one-line summary for a trace."""
    url = trace.meta.request.url
    # Strip base URL to show relative path
    relative = url
    if url.startswith(base_origin):
        relative = url[len(base_origin):]
        if base_path and relative.startswith(base_path):
            relative = relative[len(base_path):]
        if not relative:
            relative = "/"

    # Content-type (short form)
    ct = get_header(trace.meta.response.headers, "content-type") or ""
    ct_short = ct.split(";")[0].strip() if ct else ""

    # Body size
    body_size = trace.meta.response.body_size or (
        len(trace.response_body) if trace.response_body else 0
    )
    size_str = _format_size(body_size) if body_size else ""

    extras = " ".join(filter(None, [ct_short, size_str]))
    extras_part = f" ({extras})" if extras else ""

    return (
        f"  - {trace.meta.id}: {trace.meta.request.method} "
        f"{compact_url(relative) if len(relative) > 80 else relative} "
        f"→ {trace.meta.response.status}{extras_part}"
    )


def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size}B"


def _parse_candidates(items: list[Any]) -> list[ToolCandidate]:
    candidates: list[ToolCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        d = cast(dict[str, Any], item)
        name = d.get("name")
        description = d.get("description")
        trace_ids: list[Any] = d.get("trace_ids", [])
        if not name or not description or not trace_ids:
            continue
        candidates.append(
            ToolCandidate(
                name=str(name),
                description=str(description),
                trace_ids=[str(tid) for tid in trace_ids],
            )
        )
    return candidates
