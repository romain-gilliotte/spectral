"""Centralized LLM client, generic helpers, and tool_use conversation loop.

Usage::

    import cli.helpers.llm as llm

    llm.init()                          # once at startup (creates AsyncAnthropic + semaphore)
    llm.init(client=mock_client)        # in tests — inject a mock

    response = await llm.create(        # drop-in for client.messages.create
        model="claude-sonnet-4-5-20250929",
        max_tokens=2048,
        messages=[...],
    )

    data = llm.extract_json(text)       # robust JSON extraction from LLM output
    llm.save_debug(debug_dir, name, prompt, response_text)
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

MAX_CONCURRENT = 5
MAX_RETRIES = 3
FALLBACK_BACKOFF = 2.0  # seconds, doubled each retry


def init(client: Any = None, max_concurrent: int = MAX_CONCURRENT) -> None:
    """Initialize the module-level client and semaphore.

    Call once before any ``create()`` call.  In production, *client* is
    ``None`` and a real ``AsyncAnthropic`` is created.  In tests, pass a
    mock client.
    """
    global _client, _semaphore

    if client is not None:
        _client = client
    else:
        import anthropic

        _client = anthropic.AsyncAnthropic()

    _semaphore = asyncio.Semaphore(max_concurrent)


def reset() -> None:
    """Clear the module-level client and semaphore (for tests)."""
    global _client, _semaphore
    _client = None
    _semaphore = None


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


async def call_with_tools(
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
