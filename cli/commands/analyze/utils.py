"""Shared utility functions for the analysis pipeline."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from cli.helpers.http import get_header as get_header


def pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a path pattern like /api/users/{user_id}/orders to a regex."""
    parts = re.split(r"\{[^}]+\}", pattern)
    placeholders = re.findall(r"\{[^}]+\}", pattern)

    regex = ""
    for i, part in enumerate(parts):
        regex += re.escape(part)
        if i < len(placeholders):
            regex += r"[^/]+"

    return re.compile(f"^{regex}$")


def compact_url(url: str) -> str:
    """Strip query string and replace long base64-encoded path segments with a placeholder.

    Only compacts segments that are >60 chars AND decode to valid UTF-8 text via base64.
    This avoids false positives on hex IDs, normal words, etc.
    """
    from cli.commands.analyze.tools import execute_decode_base64

    parsed = urlparse(url)
    segments = parsed.path.split("/")
    compacted: list[str] = []
    for seg in segments:
        if len(seg) > 60:
            try:
                text = execute_decode_base64(seg)
                if not text.startswith("<binary:"):
                    compacted.append(f"<base64:{len(seg)}chars>")
                    continue
            except ValueError:
                pass
        compacted.append(seg)
    return f"{parsed.scheme}://{parsed.netloc}{'/'.join(compacted)}"


def truncate_json(obj: Any, max_keys: int = 10) -> Any:
    """Truncate a JSON-like object for LLM consumption."""
    if isinstance(obj, dict):
        items: list[tuple[str, Any]] = list(obj.items())[:max_keys]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        return {k: truncate_json(v, max_keys) for k, v in items}
    if isinstance(obj, list):
        items_list: list[Any] = obj[:3]  # pyright: ignore[reportUnknownVariableType]
        return [truncate_json(item, max_keys) for item in items_list]
    if isinstance(obj, str) and len(obj) > 200:
        return obj[:200] + "..."
    return obj


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redact long token values but keep header structure visible."""
    sanitized: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in ("authorization", "cookie", "set-cookie") and len(v) > 30:
            sanitized[k] = v[:30] + "...[redacted]"
        else:
            sanitized[k] = v
    return sanitized
