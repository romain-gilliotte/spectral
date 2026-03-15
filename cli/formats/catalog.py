"""Pydantic models for the community tool catalog."""

from __future__ import annotations

from pydantic import BaseModel, RootModel


class CatalogToken(BaseModel):
    """GitHub OAuth token for catalog operations (catalog_token.json)."""

    access_token: str
    username: str


class CatalogManifest(BaseModel):
    """Metadata for a published tool collection."""

    display_name: str
    description: str
    spectral_version: str


class CatalogSource(BaseModel):
    """Provenance info for tools installed from the catalog."""

    username: str
    app_name: str


class ToolExecStats(BaseModel):
    """Per-tool execution statistics (stats.json values)."""

    call_count: int = 0
    success_count: int = 0
    error_count: int = 0
    last_called_at: float | None = None
    last_status_code: int | None = None
    avg_latency_ms: float = 0.0


class ToolStats(RootModel[dict[str, ToolExecStats]]):
    """Container for all tool stats in an app (stats.json).

    Serializes as a flat dict: ``{"<tool_name>": {...}, ...}``.
    """
