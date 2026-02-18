"""HTTP header utilities."""

from __future__ import annotations

from cli.formats.capture_bundle import Header


def get_header(headers: list[Header], name: str) -> str | None:
    """Get a header value by name (case-insensitive, first match wins)."""
    name_lower = name.lower()
    for h in headers:
        if h.name.lower() == name_lower:
            return h.value
    return None
