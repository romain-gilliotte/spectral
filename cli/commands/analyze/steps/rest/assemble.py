"""Step: Assemble all pipeline components into an OpenAPI 3.1 dict."""

from __future__ import annotations

from typing import Any, cast

from cli.commands.analyze.steps.base import Step
from cli.commands.analyze.steps.rest.extraction import (
    has_auth_header_or_cookie,
)
from cli.commands.analyze.steps.rest.types import (
    EndpointSpec,
    SpecComponents,
)
from cli.commands.analyze.steps.types import AuthInfo
from cli.commands.capture.types import Trace


class AssembleStep(Step[SpecComponents, dict[str, Any]]):
    """Combine all pipeline components into an OpenAPI 3.1 dict."""

    name = "assemble"

    def __init__(self, traces: list[Trace] | None = None) -> None:
        super().__init__()
        self._traces = traces or []

    async def _execute(self, input: SpecComponents) -> dict[str, Any]:
        return build_openapi_dict(input, self._traces)


def build_openapi_dict(
    components: SpecComponents, traces: list[Trace] | None = None
) -> dict[str, Any]:
    """Build an OpenAPI 3.1 dictionary from pipeline components."""
    openapi: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": components.app_name,
            "description": f"API specification for {components.app_name}",
            "version": "1.0.0",
        },
        "servers": [],
        "paths": {},
        "components": {"securitySchemes": {}, "schemas": {}},
    }

    # Servers
    if components.base_url:
        servers: list[dict[str, Any]] = openapi["servers"]
        servers.append({"url": components.base_url})

    # Security schemes
    _add_security_schemes(openapi, components.auth)

    # Paths
    for endpoint in components.endpoints:
        path = endpoint.path
        method = endpoint.method.lower()

        if path not in openapi["paths"]:
            openapi["paths"][path] = {}

        operation = _build_operation(endpoint, components.auth)
        paths: dict[str, Any] = openapi["paths"]
        paths[path][method] = operation

    return openapi


def _add_security_schemes(openapi: dict[str, Any], auth: AuthInfo) -> None:
    """Add security scheme definitions based on detected auth."""
    if auth.type == "bearer_token":
        openapi["components"]["securitySchemes"]["bearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
        }
    elif auth.type == "basic":
        openapi["components"]["securitySchemes"]["basicAuth"] = {
            "type": "http",
            "scheme": "basic",
        }
    elif auth.type == "cookie":
        openapi["components"]["securitySchemes"]["cookieAuth"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": "session",
        }
    elif auth.type == "api_key":
        header_name = auth.token_header or "X-API-Key"
        openapi["components"]["securitySchemes"]["apiKeyAuth"] = {
            "type": "apiKey",
            "in": "header",
            "name": header_name,
        }


def _params_from_schema(
    schema: dict[str, Any] | None, location: str
) -> list[dict[str, Any]]:
    """Build OpenAPI parameter objects from an annotated schema."""
    if not schema:
        return []
    required_set = set(schema.get("required", []))
    params: list[dict[str, Any]] = []
    for name, prop in schema.get("properties", {}).items():
        prop_clean = _observed_to_examples(prop)
        p: dict[str, Any] = {
            "name": name,
            "in": location,
            "schema": prop_clean,
        }
        if name in required_set:
            p["required"] = True
        if prop.get("description"):
            p["description"] = prop["description"]
        params.append(p)
    return params


def _build_operation(
    endpoint: EndpointSpec, auth: AuthInfo
) -> dict[str, Any]:
    """Build an OpenAPI operation object for an endpoint."""
    operation: dict[str, Any] = {
        "operationId": endpoint.id,
        "summary": endpoint.description or f"{endpoint.method} {endpoint.path}",
    }

    # Tags from path
    tag = _extract_tag(endpoint.path)
    if tag:
        operation["tags"] = [tag]

    # Parameters (path + query) from annotated schemas
    parameters: list[dict[str, Any]] = []
    parameters.extend(_params_from_schema(endpoint.request.path_schema, "path"))
    parameters.extend(_params_from_schema(endpoint.request.query_schema, "query"))

    if parameters:
        operation["parameters"] = parameters

    # Request body from annotated schema
    if endpoint.request.body_schema:
        content_type = endpoint.request.content_type or "application/json"
        operation["requestBody"] = {
            "required": True,
            "content": {
                content_type: {
                    "schema": _observed_to_examples(endpoint.request.body_schema)
                }
            },
        }

    # Responses
    operation["responses"] = {}
    for resp in endpoint.responses:
        resp_obj: dict[str, Any] = {
            "description": resp.business_meaning or f"Status {resp.status}",
        }
        if resp.schema_:
            ct = resp.content_type or "application/json"
            schema_value = _observed_to_examples(resp.schema_)
            media_type: dict[str, Any] = {"schema": schema_value}
            if resp.example_body is not None:
                media_type["example"] = resp.example_body
            resp_obj["content"] = {ct: media_type}
        operation["responses"][str(resp.status)] = resp_obj

    if not operation["responses"]:
        operation["responses"] = {"200": {"description": "Successful response"}}

    # Rate limit extension
    if endpoint.rate_limit:
        operation["x-rate-limit"] = endpoint.rate_limit

    # Security
    if endpoint.requires_auth and auth.type:
        if auth.type == "bearer_token":
            operation["security"] = [{"bearerAuth": []}]
        elif auth.type == "basic":
            operation["security"] = [{"basicAuth": []}]
        elif auth.type == "cookie":
            operation["security"] = [{"cookieAuth": []}]
        elif auth.type == "api_key":
            operation["security"] = [{"apiKeyAuth": []}]

    return operation


def _observed_to_examples(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert ``observed`` lists to OpenAPI ``examples`` values recursively.

    Each property that carries an ``observed`` list gets ``examples`` set to
    the observed values.  The ``observed`` key is then removed (it is not
    valid OpenAPI).  Recurses into ``properties`` and ``items``.
    """
    out = dict(schema)
    observed = out.pop("observed", None)
    if observed:
        out["examples"] = observed
    if "properties" in out:
        out["properties"] = {
            k: _observed_to_examples(v) for k, v in out["properties"].items()
        }
    if "items" in out and isinstance(out["items"], dict):
        out["items"] = _observed_to_examples(cast(dict[str, Any], out["items"]))
    return out


def _extract_tag(path: str) -> str:
    """Extract a tag from the path (first meaningful segment)."""
    segments = [s for s in path.strip("/").split("/") if s and not s.startswith("{")]
    # Skip common prefixes like "api", "v1", etc.
    for seg in segments:
        if seg.lower() not in ("api", "v1", "v2", "v3", "rest"):
            return seg
    return segments[-1] if segments else ""


def detect_requires_auth(traces: list[Trace]) -> bool:
    """Check if any trace in a group has auth headers or cookies."""
    return any(has_auth_header_or_cookie(t) for t in traces)
