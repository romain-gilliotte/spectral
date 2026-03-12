"""Shared context builder for prompt caching across analysis steps.

Provides a byte-identical first system block (base URL + session timeline)
that can be shared across auth, MCP identify, and MCP build_tool steps.
Anthropic caches on exact prefix match, so identical first blocks = cache hit.
"""

from __future__ import annotations

from urllib.parse import urlparse

from cli.commands.capture.types import CaptureBundle, Trace
from cli.helpers.http import compact_url, get_header


def build_shared_context(bundle: CaptureBundle, base_url: str) -> str:
    """Build the shared system block: base URL + session timeline.

    This is pure data with no task-specific framing, so it can be
    reused as the first system block across different analysis steps.
    """
    timeline = _build_timeline_text(bundle, base_url)
    return f"## Base URL\n{base_url}\n\n## Session timeline\n{timeline}"


def _build_timeline_text(bundle: CaptureBundle, base_url: str) -> str:
    """Build a chronological timeline string from the bundle's timeline events."""
    parsed_base = urlparse(base_url)
    base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
    base_path = parsed_base.path.rstrip("/")

    trace_index = {t.meta.id: t for t in bundle.traces}
    context_index = {c.meta.id: c for c in bundle.contexts}

    lines: list[str] = []
    for event in bundle.timeline.events:
        if event.type == "context":
            ctx = context_index.get(event.ref)
            if ctx is None:
                continue
            text = ctx.meta.element.text or ctx.meta.element.selector
            lines.append(
                f"\U0001f5b1 [{ctx.meta.action}] \"{text}\" on {ctx.meta.page.url}"
            )
        elif event.type == "trace":
            trace = trace_index.get(event.ref)
            if trace is None:
                continue
            lines.append(_trace_timeline_line(trace, base_origin, base_path))

    return "\n".join(lines)


def _trace_timeline_line(
    trace: Trace, base_origin: str, base_path: str
) -> str:
    """Build a chronological timeline line for a trace."""
    url = trace.meta.request.url
    relative = url
    if url.startswith(base_origin):
        relative = url[len(base_origin):]
        if base_path and relative.startswith(base_path):
            relative = relative[len(base_path):]
        if not relative:
            relative = "/"

    ct = get_header(trace.meta.response.headers, "content-type") or ""
    ct_short = ct.split(";")[0].strip() if ct else ""

    body_size = trace.meta.response.body_size or (
        len(trace.response_body) if trace.response_body else 0
    )
    size_str = _format_size(body_size) if body_size else ""

    extras = " ".join(filter(None, [ct_short, size_str]))
    extras_part = f" ({extras})" if extras else ""

    return (
        f"\U0001f310 {trace.meta.id}: {trace.meta.request.method} "
        f"{compact_url(relative) if len(relative) > 80 else relative} "
        f"\u2192 {trace.meta.response.status}{extras_part}"
    )


def _format_size(size: int) -> str:
    """Format a byte size into a human-readable string."""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size}B"
