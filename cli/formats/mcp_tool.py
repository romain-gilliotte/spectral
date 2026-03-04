"""Pydantic models for MCP tool definitions, request templates, and token state."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ToolRequest(BaseModel):
    """HTTP request template for an MCP tool."""

    method: str
    path: str
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


class TokenState(BaseModel):
    """Persisted authentication state (token.json)."""

    headers: dict[str, str]
    refresh_token: str | None = None
    expires_at: float | None = None
    obtained_at: float
