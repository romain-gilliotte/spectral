"""Generate cURL example scripts from enriched API spec."""

from __future__ import annotations

import json
from pathlib import Path

from cli.formats.api_spec import ApiSpec, EndpointSpec


def generate_curl_scripts(spec: ApiSpec, output_path: str | Path) -> None:
    """Generate cURL script files from an enriched API spec."""
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    # One script per endpoint
    for endpoint in spec.protocols.rest.endpoints:
        script = build_curl_script(endpoint, spec)
        filename = f"{endpoint.id}.sh"
        (output_path / filename).write_text(script)

    # All-in-one script
    all_script = build_all_curl_script(spec)
    (output_path / "all_requests.sh").write_text(all_script)


def build_curl_script(endpoint: EndpointSpec, spec: ApiSpec) -> str:
    """Build a single cURL script for an endpoint."""
    lines = ["#!/usr/bin/env bash", ""]
    lines.append(f"# {endpoint.business_purpose or endpoint.method + ' ' + endpoint.path}")
    if endpoint.user_story:
        lines.append(f"# {endpoint.user_story}")
    lines.append("")

    curl_cmd = _build_curl_command(endpoint, spec)
    lines.append(curl_cmd)
    lines.append("")

    return "\n".join(lines)


def build_all_curl_script(spec: ApiSpec) -> str:
    """Build a single script with all cURL commands."""
    lines = [
        "#!/usr/bin/env bash",
        "",
        f"# {spec.name} - All API requests",
        f"# Base URL: {spec.protocols.rest.base_url}",
        "",
    ]

    if spec.auth.type and spec.auth.type != "none":
        lines.append('# Set your auth token')
        lines.append('TOKEN="${API_TOKEN:-your-token-here}"')
        lines.append("")

    for endpoint in spec.protocols.rest.endpoints:
        lines.append(f"# --- {endpoint.id} ---")
        if endpoint.business_purpose:
            lines.append(f"# {endpoint.business_purpose}")
        curl_cmd = _build_curl_command(endpoint, spec)
        lines.append(curl_cmd)
        lines.append("")

    return "\n".join(lines)


def _build_curl_command(endpoint: EndpointSpec, spec: ApiSpec) -> str:
    """Build a cURL command string for an endpoint."""
    base_url = spec.protocols.rest.base_url.rstrip("/")
    path = endpoint.path

    # Replace path parameters with example values
    for param in endpoint.request.parameters:
        if param.location == "path":
            example = param.example or f"<{param.name}>"
            path = path.replace("{" + param.name + "}", str(example))

    url = f"{base_url}{path}"

    # Add query parameters
    query_params = [p for p in endpoint.request.parameters if p.location == "query"]
    if query_params:
        query_parts: list[str] = []
        for p in query_params:
            val = p.example or f"<{p.name}>"
            query_parts.append(f"{p.name}={val}")
        url += "?" + "&".join(query_parts)

    parts = ["curl"]

    # Method
    if endpoint.method.upper() != "GET":
        parts.append(f"-X {endpoint.method.upper()}")

    # URL
    parts.append(f"'{url}'")

    # Auth header
    if endpoint.requires_auth and spec.auth.type:
        header = spec.auth.token_header or "Authorization"
        prefix = spec.auth.token_prefix
        if prefix:
            parts.append(f"-H '{header}: {prefix} $TOKEN'")
        else:
            parts.append(f"-H '{header}: $TOKEN'")

    # Request body
    body_params = [p for p in endpoint.request.parameters if p.location == "body"]
    if body_params:
        body = {}
        for p in body_params:
            if p.example is not None:
                body[p.name] = p.example
            else:
                body[p.name] = f"<{p.name}>"
        ct = endpoint.request.content_type or "application/json"
        parts.append(f"-H 'Content-Type: {ct}'")
        parts.append(f"-d '{json.dumps(body)}'")

    return " \\\n  ".join(parts)
