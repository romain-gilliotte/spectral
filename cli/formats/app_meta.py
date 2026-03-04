"""Pydantic model for per-app metadata (app.json)."""

from pydantic import BaseModel


class AppMeta(BaseModel):
    name: str
    display_name: str = ""
    created_at: str
    updated_at: str
    base_url: str | None = None
