"""Pydantic model for per-app metadata (app.json)."""

from __future__ import annotations

from pydantic import BaseModel

from cli.formats.catalog import CatalogSource


class AppMeta(BaseModel):
    name: str
    display_name: str = ""
    created_at: str
    updated_at: str
    base_urls: list[str] = []
    catalog_source: CatalogSource | None = None
