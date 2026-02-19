"""REST-specific types passed between pipeline steps.

These dataclasses represent data flowing between the REST analysis steps:
endpoint grouping, mechanical extraction, enrichment, and OpenAPI assembly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cli.commands.analyze.steps.types import AuthInfo, Correlation
from cli.commands.capture.types import Trace

# -- Endpoint grouping -------------------------------------------------------


@dataclass
class EndpointGroup:
    """An LLM-identified endpoint group."""

    method: str
    pattern: str
    urls: list[str] = field(default_factory=lambda: [])


# -- Endpoint spec types (REST-specific) ------------------------------------


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


# -- Inputs for REST mechanical steps ----------------------------------------


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
