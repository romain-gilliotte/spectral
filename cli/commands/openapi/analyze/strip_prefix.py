"""Strip base URL path prefix from endpoint patterns."""

from __future__ import annotations

from urllib.parse import urlparse

from cli.commands.openapi.analyze.types import EndpointGroup


async def strip_prefix(groups: list[EndpointGroup], base_url: str) -> list[EndpointGroup]:
    """Remove the base URL path prefix from endpoint patterns.

    e.g. base_url="https://app.example.com/api" + pattern="/api/foo" -> pattern="/foo"
    """
    base_path = urlparse(base_url).path.rstrip("/")
    if not base_path or base_path == "/":
        return groups

    for group in groups:
        if group.pattern.startswith(base_path):
            group.pattern = group.pattern[len(base_path):] or "/"

    return groups
