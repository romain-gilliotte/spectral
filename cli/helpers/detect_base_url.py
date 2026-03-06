"""Detect the business API base URL from captured traffic."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from cli.commands.capture.types import CaptureBundle
from cli.helpers.http import compact_url
from cli.helpers.json import extract_json
import cli.helpers.llm as llm
from cli.helpers.llm_tools import INVESTIGATION_TOOLS, TOOL_EXECUTORS


@dataclass(frozen=True, order=True)
class MethodUrlPair:
    """An observed (HTTP method, URL) pair from a single trace."""
    method: str
    url: str


async def detect_base_url(bundle: CaptureBundle, app_name: str) -> str:
    """Detect the business API base URL from a capture bundle.

    Checks app.json cache first, then falls back to LLM detection.
    """
    # Fast path: return cached base_url from app.json if available
    cached = _load_cached_base_url(app_name)
    if cached is not None:
        return cached

    pairs = [
        MethodUrlPair(t.meta.request.method.upper(), t.meta.request.url)
        for t in bundle.traces
    ]

    counts = Counter(
        MethodUrlPair(p.method, compact_url(p.url)) for p in pairs
    )
    lines = [
        f"  {p.method} {p.url} ({n}x)" if n > 1 else f"  {p.method} {p.url}"
        for p, n in sorted(counts.items())
    ]

    prompt = f"""You are analyzing HTTP traffic captured from a web application.
Identify the base URL of the **business API** (the main application API, not CDN, analytics, tracking, fonts, or third-party services).

The base URL can be:
- Just the origin: https://api.example.com
- Origin + path prefix: https://www.example.com/api

Rules:
- Pick the single most important API base URL — the one serving the app's core business endpoints.
- Ignore CDN domains, analytics (google-analytics, hotjar, segment, etc.), ad trackers, font services, static asset hosts.
- If the API endpoints share a common path prefix (e.g. /api/v1), include it.
- A single URL called many times (e.g. POST /graphql) often indicates a GraphQL API — that's still a valid business API.
- Return ONLY the base URL string, no trailing slash.

Observed requests (call count shown when > 1):
{chr(10).join(lines)}

Respond with a compact JSON object (no indentation):
{{"base_url": "https://..."}}"""

    text = await llm.ask(
        prompt,
        label="detect_api_base_url",
        tools=INVESTIGATION_TOOLS,
        executors=TOOL_EXECUTORS,
    )

    result = extract_json(text)
    if isinstance(result, dict) and "base_url" in result:
        base_url = str(result["base_url"]).rstrip("/")
        if not base_url.startswith("http"):
            raise ValueError(f"Invalid base URL: {base_url}")
        return base_url
    raise ValueError(
        f'Expected {{"base_url": "..."}} from detect_api_base_url, got: {text[:200]}'
    )


def _load_cached_base_url(app_name: str) -> str | None:
    """Check app.json for a previously saved base_url."""
    try:
        from cli.helpers.storage import load_app_meta
        meta = load_app_meta(app_name)
        if meta.base_url:
            return meta.base_url
    except Exception:
        pass
    return None
