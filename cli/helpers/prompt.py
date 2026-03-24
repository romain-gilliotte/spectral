"""Load and render Jinja2 prompt templates from cli/prompts/."""

from __future__ import annotations

import importlib.resources
import json
from typing import Any

from jinja2 import Environment, StrictUndefined

from cli.helpers.http import sanitize_headers
from cli.helpers.json import minified, truncate_json

_env = Environment(
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
)


def _headers_to_dict(headers: list[Any]) -> dict[str, str]:
    """Convert a list of Header objects to a dict."""
    return {h.name: h.value for h in headers}


def _dict_join(d: dict[str, str], kv_sep: str, pair_sep: str) -> str:
    """Join dict entries as ``key<kv_sep>value`` separated by *pair_sep*."""
    return pair_sep.join(f"{k}{kv_sep}{v}" for k, v in d.items())


_AUTH_KEYWORDS: frozenset[str] = frozenset(
    {
        "auth",
        "login",
        "token",
        "oauth",
        "session",
        "signin",
        "verification",
        "otp",
        "verify",
        "password",
        "credential",
        "callback",
        "refresh",
    }
)


def _is_auth_trace(trace: Any) -> bool:
    """Return True if *trace* looks auth-related."""
    url_lower: str = trace.meta.request.url.lower()
    req_headers = {h.name.lower() for h in trace.meta.request.headers}
    return (
        "authorization" in req_headers
        or any(kw in url_lower for kw in _AUTH_KEYWORDS)
        or trace.meta.response.status in (401, 403)
    )


def _parse(blob: str) -> Any | None:
    """Parse the request body as JSON, returning None on failure."""
    if not blob:
        return None
    try:
        return json.loads(blob)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


_env.filters["parse"] = _parse  # pyright: ignore[reportArgumentType]
_env.filters["minified"] = minified  # pyright: ignore[reportArgumentType]
_env.filters["truncate_json"] = truncate_json  # pyright: ignore[reportArgumentType]
_env.filters["sanitize_headers"] = sanitize_headers  # pyright: ignore[reportArgumentType]
_env.filters["headers_to_dict"] = _headers_to_dict  # pyright: ignore[reportArgumentType]
_env.filters["dict_join"] = _dict_join  # pyright: ignore[reportArgumentType]
_env.filters["is_auth_trace"] = _is_auth_trace  # pyright: ignore[reportArgumentType]


def _read_template(name: str) -> str:
    """Read a .j2 file from the cli.prompts package."""
    ref = importlib.resources.files("cli.prompts").joinpath(name)
    return ref.read_text(encoding="utf-8")


def render(template: str, **variables: object) -> str:
    """Load *template* from cli/prompts/ and render it with *variables*."""
    source = _read_template(template)
    return _env.from_string(source).render(**variables)


def load(template: str) -> str:
    """Load *template* from cli/prompts/ and return it as-is (no variables)."""
    return _read_template(template)
