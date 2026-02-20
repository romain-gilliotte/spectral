"""Centralized LLM client, generic helpers, and tool_use conversation loop.

Usage::

    import cli.helpers.llm as llm

    llm.init()                          # once at startup (creates AsyncAnthropic + semaphore)
    llm.init(client=mock_client)        # in tests — inject a mock
    llm.init(debug_dir=Path("debug/…"))  # enable debug logging of LLM calls

    response = await llm.create(        # drop-in for client.messages.create
        model="claude-sonnet-4-5-20250929",
        max_tokens=2048,
        messages=[...],
    )

    data = llm.extract_json(text)       # robust JSON extraction from LLM output
    llm.save_debug(name, prompt, response_text)
    text = await llm.call_with_tools(model, messages, tools, executors)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from cli.helpers.console import console

_client: Any = None
_semaphore: asyncio.Semaphore | None = None
_debug_dir: Path | None = None

MAX_CONCURRENT = 5
MAX_RETRIES = 3
FALLBACK_BACKOFF = 2.0  # seconds, doubled each retry


def init(
    client: Any = None,
    max_concurrent: int = MAX_CONCURRENT,
    debug_dir: Path | None = None,
) -> None:
    """Initialize the module-level client, semaphore, and optional debug directory.

    Call once before any ``create()`` call.  In production, *client* is
    ``None`` and a real ``AsyncAnthropic`` is created.  In tests, pass a
    mock client.  When *debug_dir* is set, LLM prompts and responses are
    saved there by ``save_debug()``.
    """
    global _client, _semaphore, _debug_dir

    if client is not None:
        _client = client
    else:
        import anthropic

        _client = anthropic.AsyncAnthropic()

    _semaphore = asyncio.Semaphore(max_concurrent)
    _debug_dir = debug_dir


def reset() -> None:
    """Clear the module-level client, semaphore, and debug directory (for tests)."""
    global _client, _semaphore, _debug_dir
    _client = None
    _semaphore = None
    _debug_dir = None


async def create(*, label: str = "", **kwargs: Any) -> Any:
    """Call ``client.messages.create`` with semaphore gating and rate-limit retry.

    Retries up to ``_MAX_RETRIES`` times on ``RateLimitError``, reading the
    ``retry-after`` response header when available (falls back to exponential
    backoff starting at 2 s).  Non-rate-limit errors propagate immediately.
    """
    import anthropic

    if _client is None or _semaphore is None:
        raise RuntimeError("cli.helpers.llm not initialized — call llm.init() first")

    delay = FALLBACK_BACKOFF

    async with _semaphore:
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await _client.messages.create(**kwargs)
            except anthropic.RateLimitError as exc:
                if attempt >= MAX_RETRIES:
                    tag = f" ({label})" if label else ""
                    console.print(
                        f"  [red]Rate limit exceeded{tag}, "
                        f"giving up after {MAX_RETRIES} retries[/red]"
                    )
                    raise

                # Try to read the retry-after header from the response.
                wait = _parse_retry_after(exc)
                if wait is None:
                    wait = delay
                    delay *= 2

                tag = f" ({label})" if label else ""
                console.print(
                    f"  [yellow]Rate limited{tag}, "
                    f"retrying in {wait:.1f}s...[/yellow]"
                )
                await asyncio.sleep(wait)

    # Unreachable, but keeps type-checkers happy.
    raise RuntimeError("unreachable")  # pragma: no cover


def _parse_retry_after(exc: Exception) -> float | None:
    """Extract ``retry-after`` seconds from an Anthropic error response."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Generic LLM helpers
# ---------------------------------------------------------------------------


def save_debug(call_name: str, prompt: str, response_text: str) -> None:
    """Save an LLM call's prompt and response to the debug directory."""
    if _debug_dir is None:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    path = _debug_dir / f"{ts}_{call_name}"
    path.write_text(f"=== PROMPT ===\n{prompt}\n\n=== RESPONSE ===\n{response_text}\n")


def save_debug_conversation(call_name: str, turns: list[dict[str, Any]]) -> None:
    """Save a multi-turn tool conversation to the debug directory.

    Uses the same plain-text format as ``save_debug`` with extra sections
    for tool calls and their results.
    """
    if _debug_dir is None:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    path = _debug_dir / f"{ts}_{call_name}"

    parts: list[str] = []
    for turn in turns:
        role = turn.get("role", "")
        if role == "user":
            parts.append(f"=== PROMPT ===\n{turn.get('content', '')}")
        elif role == "assistant":
            if "content" in turn:
                parts.append(f"=== RESPONSE ===\n{turn['content']}")
            if "tool_calls" in turn:
                for tc in turn["tool_calls"]:
                    if tc.get("type") == "text":
                        parts.append(f"=== ASSISTANT TEXT ===\n{tc['text']}")
                    elif tc.get("type") == "tool_use":
                        inp = json.dumps(tc["input"], ensure_ascii=False)
                        header = f"=== TOOL: {tc['tool']}({inp}) ==="
                        if tc.get("error"):
                            header += " [ERROR]"
                        parts.append(f"{header}\n{tc['result']}")

    path.write_text("\n\n".join(parts) + "\n")


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


async def call_with_tools(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    executors: dict[str, Callable[[dict[str, Any]], str]],
    max_tokens: int = 4096,
    max_iterations: int = 10,
    call_name: str = "call",
) -> str:
    """Call the LLM with tool_use support, looping until a text response is produced."""
    debug_turns: list[dict[str, Any]] = []

    # Log the initial user prompt
    if _debug_dir is not None and messages:
        debug_turns.append({"role": "user", "content": messages[0].get("content", "")})

    for _ in range(max_iterations):
        response: Any = await create(
            label=call_name,
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
            if _debug_dir is not None:
                debug_turns.append({"role": "assistant", "content": text})
                save_debug_conversation(call_name, debug_turns)
            return text

        # Process tool calls
        messages.append({"role": "assistant", "content": response.content})
        tool_results: list[dict[str, Any]] = []
        debug_tool_calls: list[dict[str, Any]] = []
        for block in response.content:
            if getattr(block, "type", None) == "text" and block.text.strip():
                debug_tool_calls.append({"type": "text", "text": block.text})
            if getattr(block, "type", None) != "tool_use":
                continue
            executor = executors.get(block.name)
            if executor is None:
                result_str = f"Unknown tool: {block.name}"
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                        "is_error": True,
                    }
                )
                debug_tool_calls.append({
                    "type": "tool_use",
                    "tool": block.name,
                    "input": block.input,
                    "result": result_str,
                    "error": True,
                })
                continue
            try:
                result_str = executor(block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    }
                )
                debug_tool_calls.append({
                    "type": "tool_use",
                    "tool": block.name,
                    "input": block.input,
                    "result": result_str,
                })
            except Exception as exc:
                result_str = f"Error: {exc}"
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                        "is_error": True,
                    }
                )
                debug_tool_calls.append({
                    "type": "tool_use",
                    "tool": block.name,
                    "input": block.input,
                    "result": result_str,
                    "error": True,
                })
        messages.append({"role": "user", "content": tool_results})

        if _debug_dir is not None:
            debug_turns.append({"role": "assistant", "tool_calls": debug_tool_calls})

    raise ValueError(f"call_with_tools exceeded {max_iterations} iterations")
