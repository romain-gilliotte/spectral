"""Shared console and utilities for CLI commands."""

from __future__ import annotations

from rich.console import Console

console = Console()


def truncate(s: str, max_len: int) -> str:
    """Truncate a string to max_len, adding '...' if needed."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."
