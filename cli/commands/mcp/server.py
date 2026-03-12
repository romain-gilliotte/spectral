"""MCP server exposing app tools via stdio transport."""

from __future__ import annotations

import json
from typing import Any

import click

from cli.commands.mcp.request import build_request
from cli.formats.mcp_tool import ToolDefinition
from cli.helpers.auth_runtime import AuthError, get_auth_headers
from cli.helpers.storage import list_apps, list_tools, load_app_meta

# Registry: MCP tool name -> (app_name, ToolDefinition)
_registry: dict[str, tuple[str, ToolDefinition]] = {}


def _build_registry() -> None:
    """Scan all apps and register their tools."""
    _registry.clear()
    for app_meta in list_apps():
        app_name = app_meta.name
        tools = list_tools(app_name)
        for tool in tools:
            mcp_name = f"{app_name}_{tool.name}"
            _registry[mcp_name] = (app_name, tool)


def _make_mcp_tool(mcp_name: str, tool: ToolDefinition) -> Any:
    """Convert a ToolDefinition to an MCP Tool."""
    from mcp import types

    return types.Tool(
        name=mcp_name,
        description=tool.description,
        inputSchema=tool.parameters,
    )


async def _handle_call(
    app_name: str, tool: ToolDefinition, arguments: dict[str, Any]
) -> str:
    """Execute a tool call: build request, inject auth, make HTTP call."""
    import requests

    meta = load_app_meta(app_name)
    base_url = meta.base_url
    if not base_url:
        return json.dumps({"error": f"No base_url configured for app '{app_name}'"})

    # Auth cascade
    auth_headers: dict[str, str] = {}
    if tool.requires_auth:
        try:
            auth_headers = get_auth_headers(app_name)
        except AuthError:
            return json.dumps(
                {
                    "error": (
                        f"Not authenticated. "
                        f"Run 'spectral auth login {app_name}' in a terminal to log in, "
                        f"then retry."
                    )
                }
            )

    method, url, headers, body = build_request(tool, base_url, arguments, auth_headers)

    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=body
            if body is not None and tool.request.content_type == "application/json"
            else None,
            data=body
            if body is not None and tool.request.content_type != "application/json"
            else None,
            timeout=30,
        )
    except Exception as exc:
        return json.dumps({"error": f"HTTP request failed: {exc}"})

    # Format response
    result_parts = [f"HTTP {resp.status_code}"]

    resp_headers = dict(resp.headers)
    if resp_headers:
        result_parts.append(f"Headers: {json.dumps(resp_headers)}")

    result_parts.append(resp.text)

    return "\n\n".join(result_parts)


def _apply_defaults(arguments: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Insert default values for optional parameters absent from *arguments*."""
    properties = schema.get("properties", {})
    result = dict(arguments)
    for key, prop in properties.items():
        if key not in result and "default" in prop:
            result[key] = prop["default"]
    return result


def _coerce_arguments(
    arguments: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any]:
    """Coerce string arguments to the types declared in the JSON schema.

    MCP clients (including LLMs) sometimes send numeric values as strings.
    This converts them before validation so that jsonschema.validate passes.
    """
    properties = schema.get("properties", {})
    result = dict(arguments)
    for key, prop in properties.items():
        value = result.get(key)
        if not isinstance(value, str):
            continue
        declared_type = prop.get("type")
        try:
            if declared_type == "integer":
                result[key] = int(value)
            elif declared_type == "number":
                result[key] = float(value)
            elif declared_type == "boolean":
                result[key] = value.lower() in ("true", "1")
        except (ValueError, TypeError):
            pass  # leave as-is; jsonschema will report the error
    return result


def _create_server() -> Any:
    """Create and configure the MCP server."""
    import jsonschema
    from mcp import types
    from mcp.server import Server

    server = Server("spectral")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        _build_registry()
        return [_make_mcp_tool(name, tool) for name, (_, tool) in _registry.items()]

    @server.call_tool(validate_input=False)
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        if name not in _registry:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

        app_name, tool = _registry[name]
        args = arguments or {}

        # Coerce string values to declared schema types, then validate
        schema = tool.parameters
        args = _coerce_arguments(args, schema)
        try:
            jsonschema.validate(args, schema)
        except jsonschema.ValidationError as exc:
            return [
                types.TextContent(type="text", text=f"Invalid arguments: {exc.message}")
            ]

        args = _apply_defaults(args, schema)
        result = await _handle_call(app_name, tool, args)
        return [types.TextContent(type="text", text=result)]

    _ = handle_list_tools, handle_call_tool  # registered via decorators
    return server


async def run_server() -> None:
    """Start the MCP server on stdio."""
    from mcp.server.stdio import stdio_server

    server = _create_server()
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)


@click.command()
def stdio() -> None:
    """Start the MCP server on stdio.

    Exposes all app tools from managed storage as MCP tools.
    """
    import asyncio

    asyncio.run(run_server())
