"""Generate a Python client SDK from enriched API spec."""

from __future__ import annotations

from pathlib import Path

from cli.formats.api_spec import ApiSpec, EndpointSpec
from cli.helpers.naming import python_type, safe_name, to_class_name, to_identifier


def generate_python_client(spec: ApiSpec, output_path: str | Path) -> None:
    """Generate a Python client file from an enriched API spec."""
    code = build_python_client(spec)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(code)


def build_python_client(spec: ApiSpec) -> str:
    """Build Python client source code from an enriched API spec."""
    class_name = to_class_name(spec.name, suffix="Client")
    base_url = spec.protocols.rest.base_url

    lines = [
        '"""Auto-generated Python client for ' + spec.name + '."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "import requests",
        "",
        "",
        f"class {class_name}:",
        f'    """Client for {spec.name}."""',
        "",
        f'    def __init__(self, base_url: str = "{base_url}", token: str | None = None):',
        '        self.base_url = base_url.rstrip("/")',
        "        self.session = requests.Session()",
        "        if token:",
    ]

    # Set auth header based on detected auth type
    header = spec.auth.token_header or "Authorization"
    prefix = spec.auth.token_prefix
    if prefix:
        lines.append(
            f'            self.session.headers["{header}"] = f"{prefix} {{token}}"'
        )
    else:
        lines.append(f'            self.session.headers["{header}"] = token')

    lines.append("")

    # Generate methods for each endpoint
    for endpoint in spec.protocols.rest.endpoints:
        method_lines = _build_method(endpoint)
        lines.extend(method_lines)
        lines.append("")

    return "\n".join(lines) + "\n"


def _build_method(endpoint: EndpointSpec) -> list[str]:
    """Build a Python method for an endpoint."""
    method_name = to_identifier(endpoint.id, fallback="request")
    http_method = endpoint.method.lower()

    # Build parameters
    path_params = [p for p in endpoint.request.parameters if p.location == "path"]
    query_params = [p for p in endpoint.request.parameters if p.location == "query"]
    body_params = [p for p in endpoint.request.parameters if p.location == "body"]

    # Method signature
    params = ["self"]
    for p in path_params:
        params.append(f"{safe_name(p.name)}: str")
    for p in body_params:
        type_hint = python_type(p.type)
        if p.required:
            params.append(f"{safe_name(p.name)}: {type_hint}")
        else:
            params.append(f"{safe_name(p.name)}: {type_hint} | None = None")
    for p in query_params:
        type_hint = python_type(p.type)
        params.append(f"{safe_name(p.name)}: {type_hint} | None = None")

    sig = f"    def {method_name}({', '.join(params)}) -> Any:"

    lines = [sig]

    # Docstring
    doc = endpoint.business_purpose or f"{endpoint.method} {endpoint.path}"
    lines.append(f'        """{doc}"""')

    # Build URL
    path = endpoint.path
    if path_params:
        for p in path_params:
            path = path.replace("{" + p.name + "}", "{" + safe_name(p.name) + "}")
        lines.append(f'        url = f"{{self.base_url}}{path}"')
    else:
        lines.append(f'        url = f"{{self.base_url}}{path}"')

    # Query parameters
    if query_params:
        lines.append("        params = {}")
        for p in query_params:
            name = safe_name(p.name)
            lines.append(f"        if {name} is not None:")
            lines.append(f'            params["{p.name}"] = {name}')
    else:
        lines.append("        params = None")

    # Body
    if body_params:
        lines.append("        json_body = {}")
        for p in body_params:
            name = safe_name(p.name)
            if p.required:
                lines.append(f'        json_body["{p.name}"] = {name}')
            else:
                lines.append(f"        if {name} is not None:")
                lines.append(f'            json_body["{p.name}"] = {name}')
        lines.append(
            f"        response = self.session.{http_method}(url, json=json_body, params=params)"
        )
    else:
        lines.append(
            f"        response = self.session.{http_method}(url, params=params)"
        )

    lines.append("        response.raise_for_status()")
    lines.append("        if response.content:")
    lines.append("            return response.json()")
    lines.append("        return None")

    return lines
