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
        raise ValueError("Invalid JWT: expected at least 2 dot-separated parts")
    decoded: dict[str, Any] = {}
    for label, part in zip(("header", "payload"), parts[:2]):
        padded = part + "=" * (-len(part) % 4)
        raw = base64.urlsafe_b64decode(padded)
        decoded[label] = json.loads(raw)
    return minified(decoded)


# Keep legacy alias for callers that import ``execute`` directly.
execute = decode_jwt
