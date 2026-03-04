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


def truncate_json(obj: Any, max_keys: int = 10, max_depth: int = 4) -> Any:
    """Truncate a JSON-like object for LLM consumption.

    Limits breadth (max_keys per dict, 3 items per list), depth, and string length.
    """
    return _truncate(obj, max_keys, max_depth, 0)


def _truncate(obj: Any, max_keys: int, max_depth: int, depth: int) -> Any:
    if depth >= max_depth:
        if isinstance(obj, dict):
            n: int = len(obj)  # pyright: ignore[reportUnknownArgumentType]
            return {"_truncated": f"{n} keys"}
        if isinstance(obj, list):
            n = len(obj)  # pyright: ignore[reportUnknownArgumentType]
            return [f"...{n} items"]
        if isinstance(obj, str) and len(obj) > 200:
            return obj[:200] + "..."
        return obj
    if isinstance(obj, dict):
        all_items: list[tuple[str, Any]] = list(obj.items())  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        items = all_items[:max_keys]
        result = {k: _truncate(v, max_keys, max_depth, depth + 1) for k, v in items}
        if len(all_items) > max_keys:
            result["_truncated"] = f"{len(all_items) - max_keys} more keys"
        return result
    if isinstance(obj, list):
        items_list: list[Any] = obj[:3]  # pyright: ignore[reportUnknownVariableType]
        truncated = [_truncate(item, max_keys, max_depth, depth + 1) for item in items_list]
        total: int = len(obj)  # pyright: ignore[reportUnknownArgumentType]
        if total > 3:
            truncated.append(f"...{total - 3} more items")
        return truncated
    if isinstance(obj, str) and len(obj) > 200:
        return obj[:200] + "..."
    return obj


_NOISE_HEADERS: frozenset[str] = frozenset({
    # HTTP/2 pseudo-headers
    ":authority", ":method", ":path", ":scheme",
    # Browser fingerprint
    "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
    # Fetch metadata
    "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site",
    # Transport / low-value
    "accept-encoding", "user-agent", "priority",
})


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redact long token values and strip noise headers."""
    sanitized: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in _NOISE_HEADERS:
            continue
        if k.lower() in ("authorization", "cookie", "set-cookie") and len(v) > 30:
            sanitized[k] = v[:30] + "...[redacted]"
        else:
            sanitized[k] = v
    return sanitized
