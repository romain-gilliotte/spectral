"""Intermediate types passed between pipeline steps.

Every dataclass here represents data flowing from one step to the next.
Centralised in one file so the pipeline's data flow is readable without
opening each step module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cli.capture.types import Context, Trace, WsConnection, WsMessage
from cli.formats.api_spec import (
    AuthInfo,
    BusinessContext,
    EndpointSpec,
    WebSocketProtocol,
)


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
    correlations: list[Correlation]


# -- Enrichment (LLM batch call) --------------------------------------------


@dataclass
class EnrichmentContext:
    """Input for the batch enrichment + business-context LLM step."""

    endpoints: list[EndpointSpec]
    traces: list[Trace]
    app_name: str
    base_url: str
    ws_connections: list[WsConnection] | None = None


@dataclass
class EnrichmentResult:
    """Output of the batch enrichment + business-context LLM step."""

    endpoints: list[EndpointSpec]
    business_context: BusinessContext
    glossary: dict[str, str]
    api_name: str | None = None
    ws_enrichments: dict[str, str] | None = None  # ws_id -> business_purpose


# -- Final assembly ----------------------------------------------------------


@dataclass
class SpecComponents:
    """All the pieces needed to assemble the final ApiSpec."""

    app_name: str
    source_filename: str
    base_url: str
    endpoints: list[EndpointSpec]
    auth: AuthInfo
    business_context: BusinessContext
    glossary: dict[str, str]
    ws_specs: WebSocketProtocol
    api_name: str | None = None
