"""Investigation tools for LLM tool_use (decode_base64, decode_url, decode_jwt)."""

from __future__ import annotations

import base64
from collections.abc import Callable
import json
import re
from typing import Any
from urllib.parse import unquote

INVESTIGATION_TOOLS: list[dict[str, Any]] = [
    {
        "name": "decode_base64",
        "description": "Decode a base64-encoded string (standard or URL-safe, auto-padding). Returns the decoded text (UTF-8) or a hex dump if the content is binary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "description": "The base64-encoded string to decode.",
                }
            },
            "required": ["value"],
        },
    },
    {
        "name": "decode_url",
        "description": "URL-decode a percent-encoded string (e.g. %20 → space, %2F → /).",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "description": "The percent-encoded string to decode.",
                }
            },
            "required": ["value"],
        },
    },
    {
        "name": "decode_jwt",
        "description": "Decode a JWT token (without signature verification). Returns the decoded header and payload as JSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": "The JWT token string (header.payload.signature).",
                }
            },
            "required": ["token"],
        },
    },
]


def execute_decode_base64(value: str) -> str:
    """Decode a base64 string (standard or URL-safe, with auto-padding)."""
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
        raise ValueError(f"Cannot base64-decode: {value[:80]}")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"<binary: {raw.hex()}>"


def execute_decode_url(value: str) -> str:
    """URL-decode a percent-encoded string."""
    return unquote(value)


def execute_decode_jwt(token: str) -> str:
    """Decode a JWT header + payload (no signature verification)."""
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("Invalid JWT: expected at least 2 dot-separated parts")
    decoded: dict[str, Any] = {}
    for label, part in zip(("header", "payload"), parts[:2]):
        padded = part + "=" * (-len(part) % 4)
        raw = base64.urlsafe_b64decode(padded)
        decoded[label] = json.loads(raw)
    return json.dumps(decoded, indent=2)


TOOL_EXECUTORS: dict[str, Callable[[dict[str, Any]], str]] = {
    "decode_base64": lambda inp: execute_decode_base64(inp["value"]),
    "decode_url": lambda inp: execute_decode_url(inp["value"]),
    "decode_jwt": lambda inp: execute_decode_jwt(inp["token"]),
}
