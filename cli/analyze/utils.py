"""Shared utility functions for the analysis pipeline."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert a path pattern like /api/users/{user_id}/orders to a regex."""
    parts = re.split(r"\{[^}]+\}", pattern)
    placeholders = re.findall(r"\{[^}]+\}", pattern)

    regex = ""
    for i, part in enumerate(parts):
        regex += re.escape(part)
        if i < len(placeholders):
            regex += r"[^/]+"

    return re.compile(f"^{regex}$")


def _get_header(headers: list, name: str) -> str | None:
    """Get a header value by name (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.name.lower() == name_lower:
            return h.value
    return None


def _compact_url(url: str) -> str:
    """Strip query string and replace long base64-encoded path segments with a placeholder.

    Only compacts segments that are >60 chars AND decode to valid UTF-8 text via base64.
    This avoids false positives on hex IDs, normal words, etc.
    """
    from cli.analyze.tools import _execute_decode_base64

    parsed = urlparse(url)
    segments = parsed.path.split("/")
    compacted = []
    for seg in segments:
        if len(seg) > 60:
            try:
                text = _execute_decode_base64(seg)
                if not text.startswith("<binary:"):
                    compacted.append(f"<base64:{len(seg)}chars>")
                    continue
            except ValueError:
                pass
        compacted.append(seg)
    return f"{parsed.scheme}://{parsed.netloc}{'/'.join(compacted)}"


def _truncate_json(obj, max_keys: int = 10):
    """Truncate a JSON-like object for LLM consumption."""
    if isinstance(obj, dict):
        items = list(obj.items())[:max_keys]
        return {k: _truncate_json(v, max_keys) for k, v in items}
    if isinstance(obj, list):
        return [_truncate_json(item, max_keys) for item in obj[:3]]
    if isinstance(obj, str) and len(obj) > 200:
        return obj[:200] + "..."
    return obj


def _sanitize_headers(headers: dict) -> dict:
    """Redact long token values but keep header structure visible."""
    sanitized = {}
    for k, v in headers.items():
        if k.lower() in ("authorization", "cookie", "set-cookie") and len(v) > 30:
            sanitized[k] = v[:30] + "...[redacted]"
        else:
            sanitized[k] = v
    return sanitized
