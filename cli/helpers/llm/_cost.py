"""Token usage tracking and cost estimation."""

from __future__ import annotations

from typing import Any

from cli.helpers.console import console

_total_input_tokens: int = 0
_total_output_tokens: int = 0
_total_cache_read_tokens: int = 0
_total_cache_creation_tokens: int = 0
_total_cost: float = 0.0

# Per-million-token pricing: (input_$/M, output_$/M)
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


def _estimate_cost(
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


def get_usage() -> tuple[int, int]:
    """Return accumulated token usage as ``(input_tokens, output_tokens)``."""
    return (_total_input_tokens, _total_output_tokens)


def get_cache_usage() -> tuple[int, int]:
    """Return accumulated cache token usage as ``(cache_read, cache_creation)``."""
    return (_total_cache_read_tokens, _total_cache_creation_tokens)


def _record_usage(usage: Any, label: str, model: str) -> None:  # pyright: ignore[reportUnusedFunction]
    """Accumulate token counts from a PydanticAI ``RunUsage`` and print a dim summary."""
    global _total_input_tokens, _total_output_tokens
    global _total_cache_read_tokens, _total_cache_creation_tokens, _total_cost

    if usage is None:
        return

    inp = int(getattr(usage, "input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    _total_input_tokens += inp
    _total_output_tokens += out

    cache_read = int(getattr(usage, "cache_read_tokens", 0) or 0)
    cache_create = int(getattr(usage, "cache_write_tokens", 0) or 0)
    _total_cache_read_tokens += cache_read
    _total_cache_creation_tokens += cache_create

    call_cost = _estimate_cost(model, inp, out, cache_read, cache_create)
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
