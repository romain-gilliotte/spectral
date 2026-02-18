"""Step: Strip base URL path prefix from endpoint patterns."""

from __future__ import annotations

from urllib.parse import urlparse

from cli.commands.analyze.steps.base import MechanicalStep
from cli.commands.analyze.steps.types import EndpointGroup, GroupsWithBaseUrl


class StripPrefixStep(MechanicalStep[GroupsWithBaseUrl, list[EndpointGroup]]):
    """Remove the base URL path prefix from endpoint patterns.

    e.g. base_url="https://app.example.com/api" + pattern="/api/foo" -> pattern="/foo"
    """

    name = "strip_prefix"

    async def _execute(self, input: GroupsWithBaseUrl) -> list[EndpointGroup]:
        base_path = urlparse(input.base_url).path.rstrip("/")
        if not base_path or base_path == "/":
            return input.groups

        for group in input.groups:
            if group.pattern.startswith(base_path):
                group.pattern = group.pattern[len(base_path) :] or "/"

        return input.groups
