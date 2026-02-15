"""Generate OpenAPI 3.1 specification from enriched API spec."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from cli.formats.api_spec import ApiSpec, EndpointSpec


def generate_openapi(spec: ApiSpec, output_path: str | Path) -> None:
    """Generate an OpenAPI 3.1 YAML file from an enriched API spec."""
    openapi = build_openapi_dict(spec)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(openapi, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def build_openapi_dict(spec: ApiSpec) -> dict:
    """Build an OpenAPI 3.1 dictionary from an enriched API spec."""
    openapi: dict = {
        "openapi": "3.1.0",
        "info": {
            "title": spec.name,
            "description": spec.business_context.description or f"API specification for {spec.name}",
            "version": "1.0.0",
        },
        "servers": [],
        "paths": {},
        "components": {"securitySchemes": {}, "schemas": {}},
    }

    # Servers
    if spec.protocols.rest.base_url:
        openapi["servers"].append({"url": spec.protocols.rest.base_url})

    # Security schemes
    if spec.auth.type == "bearer_token":
        openapi["components"]["securitySchemes"]["bearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
        }
    elif spec.auth.type == "basic":
        openapi["components"]["securitySchemes"]["basicAuth"] = {
            "type": "http",
            "scheme": "basic",
        }
    elif spec.auth.type == "cookie":
        openapi["components"]["securitySchemes"]["cookieAuth"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": "session",
        }
    elif spec.auth.type == "api_key":
        header_name = spec.auth.token_header or "X-API-Key"
        openapi["components"]["securitySchemes"]["apiKeyAuth"] = {
            "type": "apiKey",
            "in": "header",
            "name": header_name,
        }

    # Paths
    for endpoint in spec.protocols.rest.endpoints:
        path = endpoint.path
        method = endpoint.method.lower()

        if path not in openapi["paths"]:
            openapi["paths"][path] = {}

        operation = _build_operation(endpoint, spec)
        openapi["paths"][path][method] = operation

    return openapi


def _build_operation(endpoint: EndpointSpec, spec: ApiSpec) -> dict:
    """Build an OpenAPI operation object for an endpoint."""
    operation: dict = {
        "operationId": endpoint.id,
        "summary": endpoint.business_purpose or f"{endpoint.method} {endpoint.path}",
    }

    if endpoint.user_story:
        operation["description"] = endpoint.user_story

    # Tags from path
    tag = _extract_tag(endpoint.path)
    if tag:
        operation["tags"] = [tag]

    # Parameters (path + query)
    parameters = []
    for param in endpoint.request.parameters:
        if param.location in ("path", "query"):
            p: dict = {
                "name": param.name,
                "in": param.location,
                "required": param.required,
                "schema": {"type": param.type},
            }
            desc_parts = []
            if param.business_meaning:
                desc_parts.append(param.business_meaning)
            if param.constraints:
                desc_parts.append(param.constraints)
            if desc_parts:
                p["description"] = ". ".join(desc_parts)
            if param.example:
                p["schema"]["example"] = param.example
            if param.format:
                p["schema"]["format"] = param.format
            parameters.append(p)

    if parameters:
        operation["parameters"] = parameters

    # Request body (body params)
    body_params = [p for p in endpoint.request.parameters if p.location == "body"]
    if body_params:
        properties = {}
        required = []
        for param in body_params:
            prop: dict = {"type": param.type}
            desc_parts = []
            if param.business_meaning:
                desc_parts.append(param.business_meaning)
            if param.constraints:
                desc_parts.append(param.constraints)
            if desc_parts:
                prop["description"] = ". ".join(desc_parts)
            if param.example:
                prop["example"] = param.example
            if param.format:
                prop["format"] = param.format
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        body_schema: dict = {"type": "object", "properties": properties}
        if required:
            body_schema["required"] = required

        content_type = endpoint.request.content_type or "application/json"
        operation["requestBody"] = {
            "required": True,
            "content": {content_type: {"schema": body_schema}},
        }

    # Responses
    operation["responses"] = {}
    for resp in endpoint.responses:
        resp_obj: dict = {
            "description": resp.business_meaning or f"Status {resp.status}",
        }
        if resp.schema_:
            ct = resp.content_type or "application/json"
            resp_obj["content"] = {ct: {"schema": resp.schema_}}
        operation["responses"][str(resp.status)] = resp_obj

    if not operation["responses"]:
        operation["responses"] = {"200": {"description": "Successful response"}}

    # Rate limit extension
    if endpoint.rate_limit:
        operation["x-rate-limit"] = endpoint.rate_limit

    # Security
    if endpoint.requires_auth and spec.auth.type:
        if spec.auth.type == "bearer_token":
            operation["security"] = [{"bearerAuth": []}]
        elif spec.auth.type == "basic":
            operation["security"] = [{"basicAuth": []}]
        elif spec.auth.type == "cookie":
            operation["security"] = [{"cookieAuth": []}]
        elif spec.auth.type == "api_key":
            operation["security"] = [{"apiKeyAuth": []}]

    return operation


def _extract_tag(path: str) -> str:
    """Extract a tag from the path (first meaningful segment)."""
    segments = [s for s in path.strip("/").split("/") if s and not s.startswith("{")]
    # Skip common prefixes like "api", "v1", etc.
    for seg in segments:
        if seg.lower() not in ("api", "v1", "v2", "v3", "rest"):
            return seg
    return segments[-1] if segments else ""
