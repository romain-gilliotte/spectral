"""Detect the business API base URLs from captured traffic."""

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


class BaseUrlsResponse(BaseModel):
    base_urls: list[str]

    @field_validator("base_urls")
    @classmethod
    def validate_base_urls(cls, v: list[str]) -> list[str]:
        result: list[str] = []
        for url in v:
            url = url.rstrip("/")
            if not url.startswith("http"):
                raise ValueError(f"Invalid base URL: {url}")
            result.append(url)
        return result


def detect_base_urls(bundle: CaptureBundle, app_name: str) -> list[str]:
    """Detect the business API base URLs from a capture bundle.

    Checks app.json cache first, then falls back to LLM detection.
    """
    # Fast path: return cached base_urls from app.json if available
    cached = _load_cached_base_urls(app_name)
    if cached is not None:
        return cached

    counts = Counter(
        (t.meta.request.method.upper(), compact_url(t.meta.request.url))
        for t in bundle.traces
    )

    prompt = render("detect-base-urls.j2", counts=counts)

    conv = llm.Conversation(
        label="detect_api_base_urls",
        tool_names=["decode_base64", "decode_url", "decode_jwt"],
    )
    result = conv.ask_json(prompt, BaseUrlsResponse)
    try:
        update_app_meta(app_name, base_urls=result.base_urls)
    except Exception:
        pass
    return result.base_urls


def _load_cached_base_urls(app_name: str) -> list[str] | None:
    """Check app.json for previously saved base_urls."""
    try:
        meta = load_app_meta(app_name)
        if meta.base_urls:
            return meta.base_urls
    except Exception:
        pass
    return None
