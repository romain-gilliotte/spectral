"""HTTP header utilities."""

from __future__ import annotations

from urllib.parse import urlparse

from cli.formats.capture_bundle import Header


def get_header(headers: list[Header], name: str) -> str | None:
    """Get a header value by name (case-insensitive, first match wins)."""
    name_lower = name.lower()
    for h in headers:
        if h.name.lower() == name_lower:
            return h.value
    return None


_NOISE_HEADERS: frozenset[str] = frozenset(
    {
        # HTTP/2 pseudo-headers
        ":authority",
        ":method",
        ":path",
        ":scheme",
        # Browser fingerprint
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        # Fetch metadata
        "sec-fetch-dest",
        "sec-fetch-mode",
        "sec-fetch-site",
        # Transport / low-value
        "accept-encoding",
        "priority",
    }
)


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """Strip noise headers (HTTP/2 pseudo-headers, browser fingerprint)."""
    return {k: v for k, v in headers.items() if k.lower() not in _NOISE_HEADERS}


def compact_url(url: str) -> str:
    """Strip query string and replace long base64-encoded path segments with a placeholder.

    Only compacts segments that are >60 chars AND decode to valid UTF-8 text via base64.
    This avoids false positives on hex IDs, normal words, etc.
    """
    from cli.helpers.llm.tools._decode_base64 import (
        execute as execute_decode_base64,
    )

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
    path = "/".join(compacted)
    if parsed.scheme:
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    return path
