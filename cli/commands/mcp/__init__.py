"""MCP command group — registration only."""

from __future__ import annotations

import click

from cli.commands.mcp.analyze import analyze_cmd
from cli.commands.mcp.server import stdio


@click.group()
def mcp() -> None:
    """MCP server and tool generation commands."""


mcp.add_command(stdio)
mcp.add_command(analyze_cmd, "analyze")
