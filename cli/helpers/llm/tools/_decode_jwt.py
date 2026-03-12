"""LLM tool: decode a JWT token (without signature verification)."""

from __future__ import annotations

import base64
import json
from typing import Any

from cli.helpers.json import minified


def decode_jwt(token: str) -> str:
    """Decode a JWT token (without signature verification).

    Returns the decoded header and payload as JSON.

    Args:
        token: The JWT token string (header.payload.signature).
    """
    parts = token.split(".")
    if len(parts) < 2:
        return "Invalid JWT: expected at least 2 dot-separated parts"
    decoded: dict[str, Any] = {}
    for label, part in zip(("header", "payload"), parts[:2]):
        padded = part + "=" * (-len(part) % 4)
        try:
            raw = base64.urlsafe_b64decode(padded)
        except Exception:
            decoded[label] = f"<base64 decode error for {label}>"
            continue
        try:
            decoded[label] = json.loads(raw)
        except json.JSONDecodeError:
            decoded[label] = raw.decode("utf-8", errors="replace")
    return minified(decoded)


# Keep legacy alias for callers that import ``execute`` directly.
execute = decode_jwt
