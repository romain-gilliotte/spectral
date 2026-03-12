"""Request construction from MCP tool definitions.

Pure functions — no I/O, no side effects.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, cast
from urllib.parse import urlencode, urljoin

from cli.formats.mcp_tool import ToolDefinition


def _resolve_url(base_url: str, path_template: str, params: dict[str, Any]) -> str:
    """Substitute ``{param}`` placeholders in *path_template* and join with *base_url*."""
    path = path_template
    for key, value in params.items():
        placeholder = f"{{{key}}}"
        if placeholder in path:
            path = path.replace(placeholder, str(value))
    # Ensure proper joining
    if not base_url.endswith("/"):
        base_url += "/"
    if path.startswith("/"):
        path = path[1:]
    return urljoin(base_url, path)


def _resolve_query(query_template: dict[str, Any], params: dict[str, Any]) -> dict[str, str]:
    """Replace ``{"$param": "name"}`` markers in *query_template* with values from *params*."""
    result: dict[str, str] = {}
    for key, value in query_template.items():
        resolved = _resolve_value(value, params)
        if resolved is not _Omit.OMIT:
            result[key] = str(resolved)
    return result


def _resolve_body(
    body_template: dict[str, Any] | None, params: dict[str, Any]
) -> dict[str, Any] | None:
    """Recursive walk: replace ``{"$param": "name"}`` markers in *body_template*."""
    if body_template is None:
        return None
    resolved = _resolve_value(body_template, params)
    if isinstance(resolved, dict):
        return cast(dict[str, Any], resolved)
    return body_template  # pragma: no cover


class _Omit(Enum):
    """Sentinel indicating a value should be omitted from the output."""

    OMIT = "OMIT"


def _resolve_value(value: Any, params: dict[str, Any]) -> Any:
    """Recursively resolve ``$param`` markers in a value.

    When a ``$param`` marker references a parameter absent from *params*,
    returns ``_Omit.OMIT`` so the caller can drop the key from the result.
    """
    if isinstance(value, dict):
        d = cast(dict[str, Any], value)
        # Check if this is a $param marker
        if len(d) == 1 and "$param" in d:
            param_name: str = d["$param"]
            if param_name not in params:
                return _Omit.OMIT
            return params[param_name]
        # Recurse into dict, omitting keys whose values resolve to _Omit
        return {
            k: v
            for k, v in ((k, _resolve_value(v, params)) for k, v in d.items())
            if v is not _Omit.OMIT
        }
    if isinstance(value, list):
        items = cast(list[Any], value)
        return [_resolve_value(item, params) for item in items]
    return value


def build_request(
    tool: ToolDefinition,
    base_url: str,
    params: dict[str, Any],
    auth_headers: dict[str, str] | None = None,
) -> tuple[str, str, dict[str, str], Any]:
    """Build a complete HTTP request from a tool definition.

    Returns ``(method, url, headers, body)``.
    """
    req = tool.request

    # URL with path params
    url = _resolve_url(base_url, req.path, params)

    # Query params
    query = _resolve_query(req.query, params) if req.query else {}
    if query:
        url = url + "?" + urlencode(query)

    # Headers: tool-defined + auth + content-type
    headers: dict[str, str] = {}
    headers.update(req.headers)
    if auth_headers:
        headers.update(auth_headers)

    # Body
    body: Any = None
    if req.body is not None:
        resolved_body = _resolve_body(req.body, params)
        if req.content_type == "application/x-www-form-urlencoded":
            body = urlencode(resolved_body) if resolved_body else ""
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body = resolved_body
            headers.setdefault("Content-Type", "application/json")

    return (req.method, url, headers, body)
