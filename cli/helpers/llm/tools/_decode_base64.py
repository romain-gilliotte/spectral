"""LLM tool: decode a base64-encoded string."""

from __future__ import annotations

import base64
import re


def decode_base64(value: str) -> str:
    """Decode a base64-encoded string (standard or URL-safe, auto-padding).

    Returns the decoded text (UTF-8) or a hex dump if the content is binary.

    Args:
        value: The base64-encoded string to decode.
    """
    padded = value + "=" * (-len(value) % 4)
    raw = None
    if re.fullmatch(r"[A-Za-z0-9\-_=]+", padded):
        try:
            raw = base64.urlsafe_b64decode(padded)
        except Exception:
            pass
    if raw is None and re.fullmatch(r"[A-Za-z0-9+/=]+", padded):
        try:
            raw = base64.b64decode(padded, validate=True)
        except Exception:
            pass
    if raw is None:
        return f"Cannot base64-decode: {value[:80]}"
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"<binary: {raw.hex()}>"


# Keep legacy alias for callers that import ``execute`` directly.
execute = decode_base64
