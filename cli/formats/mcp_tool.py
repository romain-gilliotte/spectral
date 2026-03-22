"""Pydantic models for MCP tool definitions, request templates, and token state."""

from __future__ import annotations

import re
from typing import Any, cast

from pydantic import BaseModel, Field, model_validator


class ToolRequest(BaseModel):
    """HTTP request template for an MCP tool."""

    method: str
    url: str = Field(pattern=r"^https?://")
    headers: dict[str, str] = {}
    query: dict[str, Any] = {}
    body: dict[str, Any] | None = None
    content_type: str = "application/json"


class ToolDefinition(BaseModel):
    """A single MCP tool corresponding to a business capability."""

    name: str
    description: str
    parameters: dict[str, Any]
    request: ToolRequest
    requires_auth: bool = True

    @model_validator(mode="after")
    def validate_param_refs(self) -> ToolDefinition:
        """Ensure every {param} and $param reference matches a declared parameter."""
        url_params = set(re.findall(r"\{(\w+)\}", self.request.url))
        properties = set(self.parameters.get("properties", {}).keys())

        missing_url = url_params - properties
        if missing_url:
            raise ValueError(
                f"URL {{param}} placeholders not in parameters: {missing_url}",
            )

        body_refs = collect_param_refs(self.request.body)
        query_refs = collect_param_refs(self.request.query)
        all_refs = body_refs | query_refs | url_params

        missing = all_refs - properties
        if missing:
            raise ValueError(
                f"$param references not in parameters: {missing}",
            )

        unused = properties - all_refs
        if unused:
            raise ValueError(
                f"Declared parameters not referenced in request: {unused}",
            )
        return self


def collect_param_refs(obj: object) -> set[str]:
    """Collect all ``$param`` reference names from a template object."""
    refs: set[str] = set()
    if isinstance(obj, dict):
        d = cast(dict[str, Any], obj)
        if len(d) == 1 and "$param" in d:
            refs.add(str(d["$param"]))
        else:
            for v in d.values():
                refs.update(collect_param_refs(v))
    elif isinstance(obj, list):
        items = cast(list[Any], obj)
        for item in items:
            refs.update(collect_param_refs(item))
    return refs


class TokenState(BaseModel):
    """Persisted authentication state (token.json)."""

    headers: dict[str, str]
    body_params: dict[str, Any] = {}
    refresh_token: str | None = None
    expires_at: float | None = None
    obtained_at: float
