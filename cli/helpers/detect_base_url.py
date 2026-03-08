"""Detect the business API base URL from captured traffic."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from pydantic import BaseModel, field_validator

from cli.commands.capture.types import CaptureBundle
from cli.helpers.http import compact_url
import cli.helpers.llm as llm
from cli.helpers.prompt import render
from cli.helpers.storage import load_app_meta, update_app_meta


@dataclass(frozen=True, order=True)
class MethodUrlPair:
    """An observed (HTTP method, URL) pair from a single trace."""
    method: str
    url: str


class BaseUrlResponse(BaseModel):
    base_url: str

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith("http"):
            raise ValueError(f"Invalid base URL: {v}")
        return v


async def detect_base_url(bundle: CaptureBundle, app_name: str) -> str:
    """Detect the business API base URL from a capture bundle.

    Checks app.json cache first, then falls back to LLM detection.
    """
    # Fast path: return cached base_url from app.json if available
    cached = _load_cached_base_url(app_name)
    if cached is not None:
        return cached

    counts = Counter(
        (t.meta.request.method.upper(), compact_url(t.meta.request.url))
        for t in bundle.traces
    )
    lines = [
        f"  {method} {url} ({n}x)" if n > 1 else f"  {method} {url}"
        for (method, url), n in sorted(counts.items())
    ]

    prompt = render("detect-base-url.j2", lines=lines)

    conv = llm.Conversation(
        label="detect_api_base_url",
        tool_names=["decode_base64", "decode_url", "decode_jwt"],
    )
    result = await conv.ask_json(prompt, BaseUrlResponse)
    try:
        update_app_meta(app_name, base_url=result.base_url)
    except Exception:
        pass
    return result.base_url


def _load_cached_base_url(app_name: str) -> str | None:
    """Check app.json for a previously saved base_url."""
    try:
        meta = load_app_meta(app_name)
        if meta.base_url:
            return meta.base_url
    except Exception:
        pass
    return None
