"""CLI command to start the MCP server."""

from __future__ import annotations

import asyncio

import click


@click.command("mcp")
def mcp() -> None:
    """Start the MCP server on stdio.

    Exposes all app tools from managed storage as MCP tools.
    """
    from cli.commands.mcp.server import run_server

    asyncio.run(run_server())
