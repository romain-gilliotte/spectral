"""Intermediate types passed between pipeline steps.

Every dataclass here represents data flowing from one step to the next.
Centralised in one file so the pipeline's data flow is readable without
opening each step module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cli.commands.capture.types import Context, Trace, WsMessage


# -- Auth types (previously Pydantic models in api_spec.py) ----------------


@dataclass
class LoginEndpointConfig:
    url: str = ""
    method: str = "POST"
    credential_fields: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    extra_fields: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    content_type: str = "application/json"
    token_response_path: str = "access_token"
    refresh_token_response_path: str = ""


@dataclass
class RefreshEndpointConfig:
    url: str = ""
    method: str = "POST"
    token_field: str = "refresh_token"
    extra_fields: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    token_response_path: str = "access_token"
    content_type: str = "application/json"


@dataclass
class AuthInfo:
    type: str = ""
    obtain_flow: str = ""
    business_process: str | None = None
    user_journey: list[str] = field(default_factory=lambda: list[str]())
    token_header: str | None = None
    token_prefix: str | None = None
    login_config: LoginEndpointConfig | None = None
    refresh_config: RefreshEndpointConfig | None = None
    discovery_notes: str | None = None


# -- Endpoint spec types (previously Pydantic models in api_spec.py) -------


@dataclass
class RequestSpec:
    content_type: str | None = None
    path_schema: dict[str, Any] | None = None
    query_schema: dict[str, Any] | None = None
    body_schema: dict[str, Any] | None = None


@dataclass
class ResponseSpec:
    status: int = 0
    content_type: str | None = None
    business_meaning: str | None = None  # LLM-inferred
    example_scenario: str | None = None  # LLM-inferred
    schema_: dict[str, Any] | None = None
    example_body: dict[str, Any] | str | list[Any] | None = None
    user_impact: str | None = None  # LLM-inferred
    resolution: str | None = None  # LLM-inferred


@dataclass
class EndpointSpec:
    id: str = ""
    path: str = ""
    method: str = ""
    description: str | None = None  # LLM-inferred
    request: RequestSpec = field(default_factory=RequestSpec)
    responses: list[ResponseSpec] = field(default_factory=lambda: list[ResponseSpec]())
    rate_limit: str | None = None
    requires_auth: bool = False
    discovery_notes: str | None = None


# -- Correlation (UI context ↔ API traces) ----------------------------------


@dataclass
class Correlation:
    """A correlation between a UI context and API traces/messages."""

    context: Context
    traces: list[Trace] = field(default_factory=lambda: list[Trace]())
    ws_messages: list[WsMessage] = field(default_factory=lambda: list[WsMessage]())


# -- Pairs extracted from raw traces ----------------------------------------


@dataclass(frozen=True, order=True)
class MethodUrlPair:
    """An observed (HTTP method, URL) pair from a single trace."""

    method: str
    url: str


# -- Endpoint grouping -------------------------------------------------------


@dataclass
class EndpointGroup:
    """An LLM-identified endpoint group."""

    method: str
    pattern: str
    urls: list[str] = field(default_factory=lambda: [])


# -- Inputs for mechanical steps ---------------------------------------------


@dataclass
class TracesWithBaseUrl:
    """Traces to filter, together with the detected base URL."""

    traces: list[Trace]
    base_url: str


@dataclass
class GroupsWithBaseUrl:
    """Endpoint groups that still carry the base URL path prefix."""

    groups: list[EndpointGroup]
    base_url: str


@dataclass
class GroupedTraceData:
    """Everything the mechanical extraction step needs."""

    groups: list[EndpointGroup]
    traces: list[Trace]


# -- Enrichment (per-endpoint LLM calls) ------------------------------------


@dataclass
class EnrichmentContext:
    """Input for the per-endpoint enrichment LLM step."""

    endpoints: list[EndpointSpec]
    traces: list[Trace]
    correlations: list[Correlation]
    app_name: str
    base_url: str


# -- Final assembly ----------------------------------------------------------


@dataclass
class SpecComponents:
    """All the pieces needed to assemble the final OpenAPI dict."""

    app_name: str
    source_filename: str
    base_url: str
    endpoints: list[EndpointSpec]
    auth: AuthInfo
