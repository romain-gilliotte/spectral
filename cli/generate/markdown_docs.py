"""Generate Markdown documentation from enriched API spec."""

from __future__ import annotations

import json
from pathlib import Path

from cli.formats.api_spec import ApiSpec, EndpointSpec


def generate_markdown_docs(spec: ApiSpec, output_path: str | Path) -> None:
    """Generate Markdown documentation files from an enriched API spec."""
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    # Main index file
    index_md = build_index_markdown(spec)
    (output_path / "index.md").write_text(index_md)

    # Per-endpoint files
    for endpoint in spec.protocols.rest.endpoints:
        endpoint_md = build_endpoint_markdown(endpoint, spec)
        filename = f"{endpoint.id}.md"
        (output_path / filename).write_text(endpoint_md)

    # Auth documentation
    if spec.auth.type:
        auth_md = build_auth_markdown(spec)
        (output_path / "authentication.md").write_text(auth_md)


def build_index_markdown(spec: ApiSpec) -> str:
    """Build the main index Markdown document."""
    lines = [
        f"# {spec.name}",
        "",
    ]

    if spec.business_context.description:
        lines.append(spec.business_context.description)
        lines.append("")

    if spec.business_context.domain:
        lines.append(f"**Domain:** {spec.business_context.domain}")
        lines.append("")

    # Base URL
    if spec.protocols.rest.base_url:
        lines.append(f"**Base URL:** `{spec.protocols.rest.base_url}`")
        lines.append("")

    # Auth summary
    if spec.auth.type:
        lines.append(f"**Authentication:** {spec.auth.type}")
        lines.append("")

    # Endpoints table
    lines.append("## Endpoints")
    lines.append("")
    lines.append("| Method | Path | Description |")
    lines.append("|--------|------|-------------|")

    for endpoint in spec.protocols.rest.endpoints:
        desc = endpoint.business_purpose or ""
        lines.append(f"| `{endpoint.method}` | `{endpoint.path}` | {desc} |")

    lines.append("")

    # WebSocket connections
    if spec.protocols.websocket.connections:
        lines.append("## WebSocket Connections")
        lines.append("")
        for ws in spec.protocols.websocket.connections:
            lines.append(f"- **{ws.id}**: `{ws.url}`")
            if ws.business_purpose:
                lines.append(f"  {ws.business_purpose}")
        lines.append("")

    # Business glossary
    if spec.business_glossary:
        lines.append("## Glossary")
        lines.append("")
        for term, definition in sorted(spec.business_glossary.items()):
            lines.append(f"- **{term}**: {definition}")
        lines.append("")

    return "\n".join(lines) + "\n"


def build_endpoint_markdown(endpoint: EndpointSpec, spec: ApiSpec) -> str:
    """Build Markdown documentation for a single endpoint."""
    lines = [
        f"# {endpoint.method} {endpoint.path}",
        "",
    ]

    if endpoint.business_purpose:
        lines.append(endpoint.business_purpose)
        lines.append("")

    if endpoint.user_story:
        lines.append(f"> {endpoint.user_story}")
        lines.append("")

    # Auth
    if endpoint.requires_auth:
        lines.append("**Requires authentication**")
        lines.append("")

    # UI Triggers
    if endpoint.ui_triggers:
        lines.append("## UI Triggers")
        lines.append("")
        for trigger in endpoint.ui_triggers:
            text = trigger.user_explanation or f"{trigger.action} on `{trigger.element_selector}`"
            lines.append(f"- {text}")
            if trigger.page_url:
                lines.append(f"  Page: `{trigger.page_url}`")
        lines.append("")

    # Request
    if endpoint.request.parameters:
        lines.append("## Request")
        lines.append("")
        if endpoint.request.content_type:
            lines.append(f"**Content-Type:** `{endpoint.request.content_type}`")
            lines.append("")

        lines.append("### Parameters")
        lines.append("")
        lines.append("| Name | Location | Type | Required | Description |")
        lines.append("|------|----------|------|----------|-------------|")
        for param in endpoint.request.parameters:
            desc = param.business_meaning or ""
            req = "Yes" if param.required else "No"
            lines.append(
                f"| `{param.name}` | {param.location} | {param.type} | {req} | {desc} |"
            )
        lines.append("")

    # Responses
    if endpoint.responses:
        lines.append("## Responses")
        lines.append("")
        for resp in endpoint.responses:
            lines.append(f"### {resp.status}")
            lines.append("")
            if resp.business_meaning:
                lines.append(resp.business_meaning)
                lines.append("")
            if resp.content_type:
                lines.append(f"**Content-Type:** `{resp.content_type}`")
                lines.append("")
            if resp.example_body:
                lines.append("**Example:**")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(resp.example_body, indent=2))
                lines.append("```")
                lines.append("")
            if resp.schema_:
                lines.append("**Schema:**")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(resp.schema_, indent=2))
                lines.append("```")
                lines.append("")

    return "\n".join(lines) + "\n"


def build_auth_markdown(spec: ApiSpec) -> str:
    """Build Markdown documentation for authentication."""
    lines = [
        "# Authentication",
        "",
        f"**Type:** {spec.auth.type}",
        "",
    ]

    if spec.auth.business_process:
        lines.append(f"**Process:** {spec.auth.business_process}")
        lines.append("")

    if spec.auth.token_header:
        lines.append(f"**Header:** `{spec.auth.token_header}`")
        if spec.auth.token_prefix:
            lines.append(f"**Prefix:** `{spec.auth.token_prefix}`")
        lines.append("")

    if spec.auth.user_journey:
        lines.append("## Authentication Flow")
        lines.append("")
        for i, step in enumerate(spec.auth.user_journey, 1):
            lines.append(f"{i}. {step}")
        lines.append("")

    if spec.auth.refresh_endpoint:
        lines.append(f"**Refresh endpoint:** `{spec.auth.refresh_endpoint}`")
        lines.append("")

    if spec.auth.discovery_notes:
        lines.append(f"**Notes:** {spec.auth.discovery_notes}")
        lines.append("")

    return "\n".join(lines) + "\n"
