"""Utilities for extracting auth data from captured traces."""

from __future__ import annotations

import json

from cli.commands.capture.types import CaptureBundle, Trace
from cli.helpers.http import get_header


def filter_traces_by_base_url(traces: list[Trace], base_url: str) -> list[Trace]:
    """Return traces whose URL starts with base_url, sorted by timestamp descending."""
    matching = [t for t in traces if t.meta.request.url.startswith(base_url)]
    matching.sort(key=lambda t: t.meta.timestamp, reverse=True)
    return matching


def find_authorization_header(filtered: list[Trace]) -> dict[str, str] | None:
    """Fast path: find Authorization header from the most recent matching trace."""
    for trace in filtered:
        value = get_header(trace.meta.request.headers, "Authorization")
        if value:
            return {"Authorization": value}
    return None


def extract_headers_by_name(
    traces: list[Trace], base_url: str, names: list[str]
) -> dict[str, str] | None:
    """Given header names, find the most recent trace with those headers and return values."""
    filtered = filter_traces_by_base_url(traces, base_url)
    names_lower = [n.lower() for n in names]

    for trace in filtered:
        headers: dict[str, str] = {}
        for h in trace.meta.request.headers:
            if h.name.lower() in names_lower:
                headers[h.name] = h.value
        if headers:
            return headers
    return None


def extract_refresh_token(bundle: CaptureBundle, base_url: str) -> str | None:
    """Find a refresh token in response bodies of POST traces matching base_url.

    Scans response bodies for JSON fields named ``refresh_token`` or
    ``refreshToken``.  Returns the value from the most recent matching trace,
    or ``None`` if no refresh token is found.
    """
    filtered = filter_traces_by_base_url(bundle.traces, base_url)

    for trace in filtered:
        if trace.meta.request.method != "POST":
            continue
        token = _parse_refresh_token(trace.response_body)
        if token is not None:
            return token

    return None


# ── Internal helpers ──────────────────────────────────────────────────────


_REFRESH_TOKEN_KEYS = ("refresh_token", "refreshToken")


def _parse_refresh_token(body: bytes) -> str | None:
    """Try to extract a refresh token value from a JSON response body."""
    if not body:
        return None
    try:
        data: object = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    obj: dict[str, object] = data  # type: ignore[assignment]
    for key in _REFRESH_TOKEN_KEYS:
        value: object = obj.get(key)
        if isinstance(value, str) and value:
            return value
    return None
