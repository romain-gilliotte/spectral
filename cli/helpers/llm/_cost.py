"""Token usage tracking and cost estimation."""

from __future__ import annotations

from typing import Any

from cli.helpers.console import console

_total_input_tokens: int = 0
_total_output_tokens: int = 0
_total_cache_read_tokens: int = 0
_total_cache_creation_tokens: int = 0
_total_cost: float = 0.0


def estimate_cost(response: Any) -> float | None:
    """Return estimated USD cost using LiteLLM's pricing database, or ``None``."""
    try:
        import litellm

        return float(litellm.completion_cost(completion_response=response))
    except Exception:
        return None


def get_usage() -> tuple[int, int]:
    """Return accumulated token usage as ``(input_tokens, output_tokens)``."""
    return (_total_input_tokens, _total_output_tokens)


def get_cache_usage() -> tuple[int, int]:
    """Return accumulated cache token usage as ``(cache_read, cache_creation)``."""
    return (_total_cache_read_tokens, _total_cache_creation_tokens)


def record_usage(response: Any, label: str, model: str) -> None:
    """Accumulate token counts from *response* and print a dim summary line."""
    global _total_input_tokens, _total_output_tokens
    global _total_cache_read_tokens, _total_cache_creation_tokens, _total_cost

    usage = getattr(response, "usage", None)
    if usage is None:
        return
    try:
        inp = int(getattr(usage, "prompt_tokens", 0) or 0)
        out = int(getattr(usage, "completion_tokens", 0) or 0)
    except (TypeError, ValueError):
        return
    _total_input_tokens += inp
    _total_output_tokens += out

    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cache_create = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    _total_cache_read_tokens += cache_read
    _total_cache_creation_tokens += cache_create

    call_cost = estimate_cost(response)
    if call_cost is not None:
        _total_cost += call_cost

    if label:
        line = f"  [dim]{label:<30} {inp:,} in · {out:,} out"
        if cache_read or cache_create:
            cache_parts: list[str] = []
            if cache_read:
                cache_parts.append(f"{cache_read:,} read")
            if cache_create:
                cache_parts.append(f"{cache_create:,} write")
            line += f" (cache: {', '.join(cache_parts)})"
        if call_cost is not None:
            line += f" · ${call_cost:.4f}"
        line += "[/dim]"
        console.print(line)


def reset_usage() -> None:
    """Reset all token counters to zero."""
    global _total_input_tokens, _total_output_tokens
    global _total_cache_read_tokens, _total_cache_creation_tokens, _total_cost
    _total_input_tokens = 0
    _total_output_tokens = 0
    _total_cache_read_tokens = 0
    _total_cache_creation_tokens = 0
    _total_cost = 0.0


def print_usage_summary() -> None:
    """Print a formatted usage summary line. Replaces cmd.py boilerplate."""
    inp_tok, out_tok = get_usage()
    if not (inp_tok or out_tok):
        return
    cost_str = f" (~${_total_cost:.2f})" if _total_cost else ""
    console.print(f"  LLM token usage: {inp_tok:,} input, {out_tok:,} output{cost_str}")
