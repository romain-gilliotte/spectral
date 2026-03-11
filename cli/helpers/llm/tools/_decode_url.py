"""LLM tool: URL-decode a percent-encoded string."""

from __future__ import annotations

from urllib.parse import unquote


def decode_url(value: str) -> str:
    """URL-decode a percent-encoded string (e.g. %20 → space, %2F → /).

    Args:
        value: The percent-encoded string to decode.
    """
    return unquote(value)


# Keep legacy alias for callers that import ``execute`` directly.
execute = decode_url
