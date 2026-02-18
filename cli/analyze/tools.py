"""LLM investigation tools and tool_use conversation loop."""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote


def save_debug(
    debug_dir: Path | None, call_name: str, prompt: str, response_text: str
) -> None:
    """Save an LLM call's prompt and response to the debug directory."""
    if debug_dir is None:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    path = debug_dir / f"{ts}_{call_name}"
    path.write_text(f"=== PROMPT ===\n{prompt}\n\n=== RESPONSE ===\n{response_text}\n")


def extract_json(text: str) -> dict[str, Any] | list[Any]:
    """Extract JSON from LLM response text, handling markdown code blocks."""
    text = text.strip()
    try:
        parsed: dict[str, Any] | list[Any] = json.loads(text)
        return parsed
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1).strip())
            return parsed
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } or [ ... ] block
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        return parsed
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}")


# --- Investigation tools for LLM tool_use ---

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


async def call_with_tools(
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    executors: dict[str, Callable[[dict[str, Any]], str]],
    max_tokens: int = 4096,
    max_iterations: int = 10,
    debug_dir: Path | None = None,
    call_name: str = "call",
) -> str:
    """Call the LLM with tool_use support, looping until a text response is produced."""
    for _ in range(max_iterations):
        response: Any = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            parts: list[str] = []
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    parts.append(block.text)
            text = "\n".join(parts)
            save_debug(debug_dir, call_name, str(messages[0].get("content", "")), text)
            return text

        # Process tool calls
        messages.append({"role": "assistant", "content": response.content})
        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            executor = executors.get(block.name)
            if executor is None:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Unknown tool: {block.name}",
                        "is_error": True,
                    }
                )
                continue
            try:
                result = executor(block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )
            except Exception as exc:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {exc}",
                        "is_error": True,
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    raise ValueError(f"call_with_tools exceeded {max_iterations} iterations")
