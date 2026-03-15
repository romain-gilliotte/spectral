"""Internal dataclasses for catalog commands."""

from __future__ import annotations

from dataclasses import dataclass, field

from cli.formats.mcp_tool import ToolDefinition


@dataclass
class CatalogEntry:
    """A single search result from the catalog backend."""

    username: str
    app_name: str
    display_name: str
    description: str
    tool_count: int
    published_at: str
    total_calls: int = 0
    success_rate: float = 0.0
    unique_users: int = 0
    installed: bool = False


@dataclass
class CatalogInstallResult:
    """Result of installing a catalog collection."""

    local_name: str
    tool_count: int
    tool_names: list[str] = field(default_factory=lambda: [])

    @staticmethod
    def from_tools(local_name: str, tools: list[ToolDefinition]) -> CatalogInstallResult:
        return CatalogInstallResult(
            local_name=local_name,
            tool_count=len(tools),
            tool_names=[t.name for t in tools],
        )
