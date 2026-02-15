"""LLM investigation tools and tool_use conversation loop."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote


def _save_debug(debug_dir: Path | None, call_name: str, prompt: str, response_text: str) -> None:
    """Save an LLM call's prompt and response to the debug directory."""
    if debug_dir is None:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    path = debug_dir / f"{ts}_{call_name}"
    path.write_text(f"=== PROMPT ===\n{prompt}\n\n=== RESPONSE ===\n{response_text}\n")


def _extract_json(text: str) -> dict | list:
    """Extract JSON from LLM response text, handling markdown code blocks."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } or [ ... ] block
    for start_char, end_char in [('{', '}'), ('[', ']')]:
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
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}")


# --- Investigation tools for LLM tool_use ---

INVESTIGATION_TOOLS = [
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


def _execute_decode_base64(value: str) -> str:
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


def _execute_decode_url(value: str) -> str:
    """URL-decode a percent-encoded string."""
    return unquote(value)


def _execute_decode_jwt(token: str) -> str:
    """Decode a JWT header + payload (no signature verification)."""
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("Invalid JWT: expected at least 2 dot-separated parts")
    decoded = {}
    for label, part in zip(("header", "payload"), parts[:2]):
        padded = part + "=" * (-len(part) % 4)
        raw = base64.urlsafe_b64decode(padded)
        decoded[label] = json.loads(raw)
    return json.dumps(decoded, indent=2)


_TOOL_EXECUTORS: dict[str, callable] = {
    "decode_base64": lambda inp: _execute_decode_base64(inp["value"]),
    "decode_url": lambda inp: _execute_decode_url(inp["value"]),
    "decode_jwt": lambda inp: _execute_decode_jwt(inp["token"]),
}


async def _call_with_tools(
    client,
    model: str,
    messages: list[dict],
    tools: list[dict],
    executors: dict[str, callable],
    max_tokens: int = 4096,
    max_iterations: int = 10,
    debug_dir: Path | None = None,
    call_name: str = "call",
) -> str:
    """Call the LLM with tool_use support, looping until a text response is produced."""
    for _ in range(max_iterations):
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            parts = []
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    parts.append(block.text)
            text = "\n".join(parts)
            _save_debug(debug_dir, call_name, messages[0]["content"], text)
            return text

        # Process tool calls
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            executor = executors.get(block.name)
            if executor is None:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Unknown tool: {block.name}",
                    "is_error": True,
                })
                continue
            try:
                result = executor(block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            except Exception as exc:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {exc}",
                    "is_error": True,
                })
        messages.append({"role": "user", "content": tool_results})

    raise ValueError(f"_call_with_tools exceeded {max_iterations} iterations")
