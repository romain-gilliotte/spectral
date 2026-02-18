"""Generate MCP (Model Context Protocol) server scaffold from enriched API spec."""

from __future__ import annotations

from pathlib import Path
import re

from cli.formats.api_spec import ApiSpec, EndpointSpec


def generate_mcp_server(spec: ApiSpec, output_path: str | Path) -> None:
    """Generate an MCP server scaffold directory from an enriched API spec."""
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    # Main server file
    server_code = build_mcp_server(spec)
    (output_path / "server.py").write_text(server_code)

    # Requirements
    requirements = "mcp>=1.0\nrequests>=2.28\n"
    (output_path / "requirements.txt").write_text(requirements)

    # README
    readme = _build_readme(spec)
    (output_path / "README.md").write_text(readme)


def build_mcp_server(spec: ApiSpec) -> str:
    """Build MCP server Python source code."""
    lines = [
        '"""MCP server for ' + spec.name + '."""',
        "",
        "from __future__ import annotations",
        "",
        "import json",
        "import os",
        "",
        "import requests",
        "from mcp.server.fastmcp import FastMCP",
        "",
        f'mcp = FastMCP("{spec.name}")',
        "",
        f'BASE_URL = os.environ.get("API_BASE_URL", "{spec.protocols.rest.base_url}")',
        'AUTH_TOKEN = os.environ.get("API_TOKEN", "")',
        "",
        "",
        "def _headers() -> dict:",
        '    """Build request headers."""',
        "    headers = {}",
        "    if AUTH_TOKEN:",
    ]

    header = spec.auth.token_header or "Authorization"
    prefix = spec.auth.token_prefix
    if prefix:
        lines.append(f'        headers["{header}"] = f"{prefix} {{AUTH_TOKEN}}"')
    else:
        lines.append(f'        headers["{header}"] = AUTH_TOKEN')

    lines.extend(
        [
            "    return headers",
            "",
            "",
        ]
    )

    # Generate a tool for each endpoint
    for endpoint in spec.protocols.rest.endpoints:
        tool_lines = _build_tool(endpoint, spec)
        lines.extend(tool_lines)
        lines.append("")

    lines.extend(
        [
            "",
            'if __name__ == "__main__":',
            "    mcp.run()",
            "",
        ]
    )

    return "\n".join(lines)


def _build_tool(endpoint: EndpointSpec, spec: ApiSpec) -> list[str]:
    """Build an MCP tool function for an endpoint."""
    func_name = _to_func_name(endpoint.id)
    description = endpoint.business_purpose or f"{endpoint.method} {endpoint.path}"

    # Parameters
    path_params = [p for p in endpoint.request.parameters if p.location == "path"]
    query_params = [p for p in endpoint.request.parameters if p.location == "query"]
    body_params = [p for p in endpoint.request.parameters if p.location == "body"]

    all_params = path_params + body_params + query_params
    param_strs: list[str] = []
    for p in all_params:
        type_hint = _python_type(p.type)
        if p.required:
            param_strs.append(f"{_safe_name(p.name)}: {type_hint}")
        else:
            param_strs.append(f"{_safe_name(p.name)}: {type_hint} | None = None")

    sig_params = ", ".join(param_strs)

    lines = [
        "@mcp.tool()",
        f"def {func_name}({sig_params}) -> str:",
        f'    """{description}"""',
    ]

    # Build URL
    path = endpoint.path
    for p in path_params:
        path = path.replace(
            "{" + p.name + "}",
            '" + str(' + _safe_name(p.name) + ') + "',
        )
    lines.append(f'    url = BASE_URL + "{path}"')

    # Query params
    if query_params:
        lines.append("    params = {}")
        for p in query_params:
            name = _safe_name(p.name)
            lines.append(f"    if {name} is not None:")
            lines.append(f'        params["{p.name}"] = {name}')
    else:
        lines.append("    params = None")

    # Body
    http_method = endpoint.method.lower()
    if body_params:
        lines.append("    json_body = {}")
        for p in body_params:
            name = _safe_name(p.name)
            if p.required:
                lines.append(f'    json_body["{p.name}"] = {name}')
            else:
                lines.append(f"    if {name} is not None:")
                lines.append(f'        json_body["{p.name}"] = {name}')
        lines.append(
            f"    response = requests.{http_method}(url, json=json_body, params=params, headers=_headers())"
        )
    else:
        lines.append(
            f"    response = requests.{http_method}(url, params=params, headers=_headers())"
        )

    lines.append("    response.raise_for_status()")
    lines.append("    return response.text")

    return lines


def _build_readme(spec: ApiSpec) -> str:
    """Build a README for the MCP server."""
    lines = [
        f"# MCP Server: {spec.name}",
        "",
        "Auto-generated MCP server providing tools for each API endpoint.",
        "",
        "## Setup",
        "",
        "```bash",
        "pip install -r requirements.txt",
        "```",
        "",
        "## Configuration",
        "",
        "Set environment variables:",
        "",
        f"- `API_BASE_URL` (default: `{spec.protocols.rest.base_url}`)",
        "- `API_TOKEN` — your authentication token",
        "",
        "## Run",
        "",
        "```bash",
        "python server.py",
        "```",
        "",
        "## Available Tools",
        "",
    ]

    for endpoint in spec.protocols.rest.endpoints:
        desc = endpoint.business_purpose or f"{endpoint.method} {endpoint.path}"
        lines.append(f"- **{endpoint.id}**: {desc}")

    lines.append("")
    return "\n".join(lines)


def _to_func_name(endpoint_id: str) -> str:
    """Convert endpoint ID to a valid Python function name."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", endpoint_id)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "api_call"


def _safe_name(name: str) -> str:
    """Make a safe Python parameter name."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if name and name[0].isdigit():
        name = "_" + name
    if name in (
        "class",
        "type",
        "import",
        "from",
        "return",
        "def",
        "if",
        "for",
        "in",
        "is",
    ):
        name = name + "_"
    return name


def _python_type(json_type: str) -> str:
    """Map JSON type to Python type hint."""
    return {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "array": "list",
        "object": "dict",
    }.get(json_type, "str")
