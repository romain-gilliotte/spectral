"""Spectral configuration model."""

from __future__ import annotations

from pydantic import BaseModel

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"


class Config(BaseModel):
    api_key: str
    model: str = DEFAULT_MODEL
