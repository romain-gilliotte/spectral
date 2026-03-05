"""Centralized LLM client with a single ``ask()`` entry point.

Usage::

    import cli.helpers.llm as llm

    llm.init(model="claude-sonnet-4-5-20250929")  # once at startup
    llm.init(client=mock_client, model="test")     # in tests — inject a mock
    llm.init(debug_dir=Path("debug/…"), model=...) # enable debug logging

    text = await llm.ask(prompt)
    text = await llm.ask(prompt, tools=..., executors=...)

    data = llm.extract_json(text)       # robust JSON extraction from LLM output
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, TypeVar, cast, overload

from pydantic import BaseModel, ValidationError

from cli.helpers.console import console

T = TypeVar("T", bound=BaseModel)

_client: Any = None
_semaphore: asyncio.Semaphore | None = None
_debug_dir: Path | None = None
_model: str | None = None
_total_input_tokens: int = 0
_total_output_tokens: int = 0
_total_cache_read_tokens: int = 0
_total_cache_creation_tokens: int = 0

MAX_CONCURRENT = 5
MAX_RETRIES = 3
FALLBACK_BACKOFF = 2.0  # seconds, doubled each retry

# Per-million-token pricing: (input_$/M, output_$/M)
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-haiku-3-5-20241022": (0.80, 4.0),
}


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float | None:
    """Return estimated USD cost, or ``None`` if model pricing is unknown.

    Cache pricing follows Anthropic rates:
    - cache reads cost 10% of the input rate
    - cache writes cost 125% of the input rate
    """
    pricing = _MODEL_PRICING.get(model)
    if pricing is None:
        return None
    inp_rate, out_rate = pricing
    return (
        input_tokens * inp_rate
        + cache_read_tokens * inp_rate * 0.1
        + cache_creation_tokens * inp_rate * 1.25
        + output_tokens * out_rate
    ) / 1_000_000


def init(
    client: Any = None,
    max_concurrent: int = MAX_CONCURRENT,
    debug_dir: Path | None = None,
    model: str | None = None,
) -> None:
    """Initialize the module-level client, semaphore, and optional debug directory.

    Call once before any ``ask()`` call.  In production, *client* is
    ``None`` and a real ``AsyncAnthropic`` is created.  In tests, pass a
    mock client.  When *debug_dir* is set, LLM prompts and responses are
    saved there automatically by ``ask()``.  When *model* is set, all
    ``ask()`` calls use it by default.
    """
    global _client, _semaphore, _debug_dir, _model
    global _total_input_tokens, _total_output_tokens
    global _total_cache_read_tokens, _total_cache_creation_tokens

    if client is not None:
        _client = client
    else:
        import os

        import anthropic
        import click

        import cli.helpers.storage as storage

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            key = storage.load_api_key()
        if not key:
            click.echo(
                "\nTo use this command, Spectral needs an Anthropic API key.\n"
                "You can create one at https://console.anthropic.com/settings/keys\n"
                f"\nThe key will be saved to {storage.store_root() / 'api_key'}\n"
            )
            key = click.prompt("API key", hide_input=True).strip()
            if not key.startswith("sk-ant-"):
                raise click.ClickException(
                    "Invalid API key format (expected a key starting with 'sk-ant-')."
                )
            storage.write_api_key(key)

        _client = anthropic.AsyncAnthropic(api_key=key)

    _semaphore = asyncio.Semaphore(max_concurrent)
    _debug_dir = debug_dir
    _model = model
    _total_input_tokens = 0
    _total_output_tokens = 0
    _total_cache_read_tokens = 0
    _total_cache_creation_tokens = 0


def reset() -> None:
    """Clear the module-level client, semaphore, debug directory, and model (for tests)."""
    global _client, _semaphore, _debug_dir, _model
    global _total_input_tokens, _total_output_tokens
    global _total_cache_read_tokens, _total_cache_creation_tokens
    _client = None
    _semaphore = None
    _debug_dir = None
    _model = None
    _total_input_tokens = 0
    _total_output_tokens = 0
    _total_cache_read_tokens = 0
    _total_cache_creation_tokens = 0


def get_usage() -> tuple[int, int]:
    """Return accumulated token usage as ``(input_tokens, output_tokens)``."""
    return (_total_input_tokens, _total_output_tokens)


def get_cache_usage() -> tuple[int, int]:
    """Return accumulated cache token usage as ``(cache_read, cache_creation)``."""
    return (_total_cache_read_tokens, _total_cache_creation_tokens)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@overload
async def ask(
    prompt: str,
    *,
    system: str | list[str] | None = None,
    max_tokens: int = 4096,
    label: str = "",
    tools: list[dict[str, Any]] | None = None,
    executors: dict[str, Callable[[dict[str, Any]], str]] | None = None,
    max_iterations: int = 10,
    response_model: type[T],
) -> T: ...


@overload
async def ask(
    prompt: str,
    *,
    system: str | list[str] | None = None,
    max_tokens: int = 4096,
    label: str = "",
    tools: list[dict[str, Any]] | None = None,
    executors: dict[str, Callable[[dict[str, Any]], str]] | None = None,
    max_iterations: int = 10,
    response_model: None = None,
) -> str: ...


async def ask(
    prompt: str,
    *,
    system: str | list[str] | None = None,
    max_tokens: int = 4096,
    label: str = "",
    tools: list[dict[str, Any]] | None = None,
    executors: dict[str, Callable[[dict[str, Any]], str]] | None = None,
    max_iterations: int = 10,
    response_model: type[T] | None = None,
) -> T | str:
    """The single entry point for calling the LLM.

    Returns the assistant's text response.  Uses the model configured
    via ``init(model=...)``.  When *tools* and *executors* are supplied,
    runs the tool-use loop via ``_call_with_tools``.  Debug logging is
    handled internally.

    When *response_model* is set, the prompt is augmented with a JSON
    instruction, the response is parsed and validated against the model,
    and a retry is attempted once on parse/validation failure.
    """
    if response_model is not None:
        prompt = (
            prompt
            + "\n\nIMPORTANT: Respond with a single minified JSON object. "
            "No commentary, no markdown fences, no explanation — only raw JSON."
        )

    model = _require_model()

    # Build system blocks with cache_control for prompt caching.
    system_blocks = _build_system_blocks(system)

    create_kwargs: dict[str, Any] = {}
    if system_blocks:
        create_kwargs["system"] = system_blocks

    if tools is not None and executors is not None:
        text = await _call_with_tools(
            model,
            [{"role": "user", "content": prompt}],
            tools,
            executors,
            max_tokens=max_tokens,
            max_iterations=max_iterations,
            call_name=label or "call",
            **create_kwargs,
        )
    else:
        response: Any = await _create(
            label=label,
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **create_kwargs,
        )

        text = _extract_text(response.content)

        _save_debug(
            label or "call",
            [{"role": "user", "content": prompt}, {"role": "assistant", "content": text}],
        )

        _check_truncation(response, max_tokens=max_tokens, label=label)

    if response_model is None:
        return text

    return await _parse_response_model(
        text, response_model, prompt, model=model, max_tokens=max_tokens, label=label,
        tools=tools, executors=executors, max_iterations=max_iterations,
        system_blocks=system_blocks,
    )


def _build_system_blocks(
    system: str | list[str] | None,
) -> list[dict[str, Any]] | None:
    """Convert *system* into a list of text blocks with ``cache_control``.

    Always produces at most **2** blocks so that the tool-use loop still
    has room for its own cache breakpoints (Anthropic caps at 4 total).

    When *system* is a list with 2+ entries the first entry becomes its
    own block (shared-context cache breakpoint) and the remaining entries
    are joined into a single second block.
    """
    if system is None:
        return None
    _CACHE_EPHEMERAL: dict[str, str] = {"type": "ephemeral"}
    if isinstance(system, str):
        return [{"type": "text", "text": system, "cache_control": _CACHE_EPHEMERAL}]
    if len(system) == 1:
        return [{"type": "text", "text": system[0], "cache_control": _CACHE_EPHEMERAL}]
    # First block = shared context (cache breakpoint for cross-step reuse).
    # Remaining blocks merged into one (cache breakpoint for intra-step reuse).
    return [
        {"type": "text", "text": system[0], "cache_control": _CACHE_EPHEMERAL},
        {"type": "text", "text": "\n\n".join(system[1:]), "cache_control": _CACHE_EPHEMERAL},
    ]


async def _parse_response_model(
    text: str,
    response_model: type[T],
    original_prompt: str,
    *,
    model: str,
    max_tokens: int,
    label: str,
    tools: list[dict[str, Any]] | None,
    executors: dict[str, Callable[[dict[str, Any]], str]] | None,
    max_iterations: int,
    system_blocks: list[dict[str, Any]] | None = None,
) -> T:
    """Parse and validate *text* against *response_model*, retrying once on failure."""
    # First attempt
    parse_error: Exception | None = None
    try:
        return _try_parse_model(text, response_model)
    except (json.JSONDecodeError, ValidationError, ValueError) as first_err:
        parse_error = first_err

    # Retry: re-call the LLM with the error
    retry_msg = (
        f"Your response could not be parsed: {parse_error}. "
        "Please respond with valid JSON matching the expected schema."
    )
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": original_prompt},
        {"role": "assistant", "content": text},
        {"role": "user", "content": retry_msg},
    ]

    extra_kwargs: dict[str, Any] = {}
    if system_blocks:
        extra_kwargs["system"] = system_blocks

    if tools is not None and executors is not None:
        retry_text = await _call_with_tools(
            model,
            messages,
            tools,
            executors,
            max_tokens=max_tokens,
            max_iterations=max_iterations,
            call_name=(label or "call") + "_retry",
            **extra_kwargs,
        )
    else:
        retry_response: Any = await _create(
            label=(label or "call") + "_retry",
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            **extra_kwargs,
        )
        retry_text = _extract_text(retry_response.content)

    return _try_parse_model(retry_text, response_model)


def _try_parse_model(text: str, response_model: type[T]) -> T:
    """Try to parse *text* as JSON and validate against *response_model*."""
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        data = extract_json(text)
    return response_model.model_validate(data)


def _require_model() -> str:
    """Return the configured model or raise if not set."""
    if _model is None:
        raise RuntimeError(
            "No model configured — call llm.init(model=...) first"
        )
    return _model


def _check_truncation(
    response: Any, *, max_tokens: int, label: str
) -> None:
    """Raise if the response was truncated due to max_tokens."""
    if getattr(response, "stop_reason", None) == "max_tokens":
        tag = f" ({label})" if label else ""
        raise ValueError(
            f"LLM response truncated{tag} (max_tokens={max_tokens}). "
            f"The prompt or expected output is too large."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _create(*, label: str = "", **kwargs: Any) -> Any:
    """Call ``client.messages.create`` with semaphore gating and rate-limit retry.

    Retries up to ``MAX_RETRIES`` times on ``RateLimitError``, reading the
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
                response = await _client.messages.create(**kwargs)
                _record_usage(response, label)
                return response
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


def _record_usage(response: Any, label: str) -> None:
    """Accumulate token counts from *response* and print a dim summary line."""
    global _total_input_tokens, _total_output_tokens
    global _total_cache_read_tokens, _total_cache_creation_tokens
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    try:
        inp = int(getattr(usage, "input_tokens", 0))
        out = int(getattr(usage, "output_tokens", 0))
    except (TypeError, ValueError):
        return
    _total_input_tokens += inp
    _total_output_tokens += out

    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cache_create = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    _total_cache_read_tokens += cache_read
    _total_cache_creation_tokens += cache_create

    if label:
        line = f"  [dim]{label:<30} {inp:,} in · {out:,} out"
        if cache_read or cache_create:
            cache_parts: list[str] = []
            if cache_read:
                cache_parts.append(f"{cache_read:,} read")
            if cache_create:
                cache_parts.append(f"{cache_create:,} write")
            line += f" (cache: {', '.join(cache_parts)})"
        if _model is not None:
            call_cost = estimate_cost(_model, inp, out, cache_read, cache_create)
            if call_cost is not None:
                line += f" · ${call_cost:.4f}"
        line += "[/dim]"
        console.print(line)


def _make_debug_path(call_name: str) -> Path | None:
    """Return the debug file path for *call_name*, or ``None`` if debug is off."""
    if _debug_dir is None:
        return None
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return _debug_dir / f"{ts}_{call_name}"


def _save_debug(
    call_name: str,
    turns: list[dict[str, Any]],
    *,
    path: Path | None = None,
) -> None:
    """Save an LLM conversation (single-shot or multi-turn) to the debug directory.

    When *path* is given, write to that file (used for incremental writes
    during tool-use loops so every iteration is visible on disk).  When
    omitted, a new timestamped path is generated.
    """
    if path is None:
        path = _make_debug_path(call_name)
    if path is None:
        return

    parts: list[str] = []
    for turn in turns:
        role = turn.get("role", "")
        if role == "user":
            content = _reformat_debug_text(str(turn.get("content", "")))
            parts.append(f"=== PROMPT ===\n{content}")
        elif role == "assistant":
            if "content" in turn:
                content = _reformat_debug_text(str(turn["content"]))
                parts.append(f"=== RESPONSE ===\n{content}")
            if "tool_calls" in turn:
                for tc in turn["tool_calls"]:
                    if tc.get("type") == "text":
                        parts.append(f"=== ASSISTANT TEXT ===\n{tc['text']}")
                    elif tc.get("type") == "tool_use":
                        inp = json.dumps(tc["input"], ensure_ascii=False)
                        header = f"=== TOOL: {tc['tool']}({inp}) ==="
                        if tc.get("error"):
                            header += " [ERROR]"
                        result = _reformat_debug_text(str(tc["result"]))
                        parts.append(f"{header}\n{result}")

    path.write_text("\n\n".join(parts) + "\n")


# ---------------------------------------------------------------------------
# Generic LLM helpers
# ---------------------------------------------------------------------------


def compact_json(obj: Any) -> str:
    """Serialize *obj* to compact JSON (no whitespace) for LLM prompts."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


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


def _readable_json(obj: Any) -> str:
    """Format *obj* as semi-compact JSON for debug readability.

    Short inner arrays/objects (<=80 chars when collapsed) are placed on a
    single line while larger structures remain indented.  Uses compact-json
    for reliable formatting.
    """
    import compact_json  # type: ignore[import-untyped]

    formatter = compact_json.Formatter()
    formatter.indent_spaces = 2
    formatter.max_inline_length = 80
    formatter.ensure_ascii = False
    return formatter.serialize(obj)


def _reformat_debug_text(text: str) -> str:
    """Reformat JSON blobs in debug prose for readability.

    Splits on newlines, tries ``json.loads`` on each line, and replaces
    parseable ones with ``_readable_json`` output.  This handles minified
    JSON lines (including those inside markdown code fences) while leaving
    non-JSON lines untouched.
    """
    lines = text.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue
        try:
            obj = json.loads(stripped)
            result.append(_readable_json(obj))
        except (json.JSONDecodeError, ValueError):
            result.append(line)
    return "\n".join(result)


def _extract_text(content: list[Any]) -> str:
    """Join all text blocks from an LLM response content list."""
    return "\n".join(
        block.text for block in content if getattr(block, "type", None) == "text"
    )


def _execute_tool(
    block: Any,
    executors: dict[str, Callable[[dict[str, Any]], str]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute a single tool_use block, returning ``(tool_result, debug_entry)``.

    Handles unknown tools and executor exceptions uniformly.
    """
    executor = executors.get(block.name)
    if executor is None:
        result_str = f"Unknown tool: {block.name}"
        is_error = True
    else:
        try:
            result_str = executor(block.input)
            is_error = False
        except Exception as exc:
            result_str = f"Error: {exc}"
            is_error = True

    tool_result: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": result_str,
    }
    if is_error:
        tool_result["is_error"] = True

    debug_entry: dict[str, Any] = {
        "type": "tool_use",
        "tool": block.name,
        "input": block.input,
        "result": result_str,
    }
    if is_error:
        debug_entry["error"] = True

    return tool_result, debug_entry


async def _call_with_tools(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    executors: dict[str, Callable[[dict[str, Any]], str]],
    max_tokens: int = 4096,
    max_iterations: int = 10,
    call_name: str = "call",
    **extra_create_kwargs: Any,
) -> str:
    """Call the LLM with tool_use support, looping until a text response is produced."""
    # Defensive copy so we never mutate the caller's list.
    tools = list(tools)

    debug_turns: list[dict[str, Any]] = []
    debug_path = _make_debug_path(call_name)

    # Log the initial user prompt
    if debug_path is not None and messages:
        debug_turns.append({"role": "user", "content": messages[0].get("content", "")})

    # --- Prompt caching breakpoints ---
    # Mark the last tool definition so all tool schemas are cached.
    _CACHE_EPHEMERAL: dict[str, str] = {"type": "ephemeral"}
    if tools:
        tools[-1] = {**tools[-1], "cache_control": _CACHE_EPHEMERAL}

    # Convert the first user message content to a content block with cache_control
    # so the (usually large) initial prompt is cached across iterations.
    if messages and isinstance(messages[0].get("content"), str):
        messages[0] = {
            **messages[0],
            "content": [
                {
                    "type": "text",
                    "text": messages[0]["content"],
                    "cache_control": _CACHE_EPHEMERAL,
                }
            ],
        }

    for _ in range(max_iterations):
        response: Any = await _create(
            label=call_name,
            model=model,
            max_tokens=max_tokens,
            tools=tools,
            messages=messages,
            **extra_create_kwargs,
        )

        if response.stop_reason == "max_tokens":
            if debug_path is not None:
                debug_turns.append({
                    "role": "assistant",
                    "content": _extract_text(response.content) + "\n[TRUNCATED]",
                })
                _save_debug(call_name, debug_turns, path=debug_path)
            raise ValueError(
                f"LLM response truncated ({call_name}, max_tokens={max_tokens}). "
                f"The prompt or expected output is too large."
            )

        if response.stop_reason != "tool_use":
            text = _extract_text(response.content)
            if debug_path is not None:
                debug_turns.append({"role": "assistant", "content": text})
                _save_debug(call_name, debug_turns, path=debug_path)
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
            tool_result, debug_entry = _execute_tool(block, executors)
            tool_results.append(tool_result)
            debug_tool_calls.append(debug_entry)

        # Rolling cache breakpoint: the new tool_result will be the latest
        # cache boundary, so remove ALL previous cache_control markers from
        # user messages (both old tool_results and the initial text block).
        # This keeps total breakpoints at: system blocks + last tool def +
        # latest tool_result (≤4).  The initial user message is still cached
        # as part of the prefix up to the tool_result breakpoint.
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for blk in cast(list[dict[str, Any]], content):
                blk.pop("cache_control", None)

        if tool_results:
            tool_results[-1] = {**tool_results[-1], "cache_control": _CACHE_EPHEMERAL}

        messages.append({"role": "user", "content": tool_results})

        if debug_path is not None:
            debug_turns.append({"role": "assistant", "tool_calls": debug_tool_calls})
            _save_debug(call_name, debug_turns, path=debug_path)

    raise ValueError(f"_call_with_tools exceeded {max_iterations} iterations")
