"""HTTP client for the Spectral catalog backend."""

from __future__ import annotations

from typing import Any

import requests

# Backend URL (DigitalOcean Function)
CATALOG_BACKEND_URL = "https://api.getspectral.sh/catalog"


class CatalogAPIError(Exception):
    """Raised when the catalog backend returns an error."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


def publish(
    github_token: str,
    app_name: str,
    manifest: dict[str, Any],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """Publish a tool collection to the catalog backend.

    Returns ``{"pr_url": "...", "branch": "..."}``.
    """
    resp = requests.post(
        f"{CATALOG_BACKEND_URL}/publish",
        json={
            "github_token": github_token,
            "app_name": app_name,
            "manifest": manifest,
            "tools": tools,
        },
        timeout=30,
    )
    if resp.status_code == 409:
        data = resp.json()
        raise CatalogAPIError(409, data.get("message", "PR already exists"))
    if not resp.ok:
        try:
            data = resp.json()
            msg = data.get("message", resp.text)
        except Exception:
            msg = resp.text
        raise CatalogAPIError(resp.status_code, msg)
    return resp.json()


def search(query: str) -> list[dict[str, Any]]:
    """Search the catalog for tool collections matching *query*."""
    resp = requests.get(
        f"{CATALOG_BACKEND_URL}/search",
        params={"q": query},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def report_stats(user_hash: str, stats: list[dict[str, Any]]) -> None:
    """Send aggregated tool execution stats to the backend (best-effort)."""
    try:
        requests.post(
            f"{CATALOG_BACKEND_URL}/stats",
            json={"user_hash": user_hash, "stats": stats},
            timeout=10,
        )
    except Exception:
        pass  # best-effort — silently ignore failures
