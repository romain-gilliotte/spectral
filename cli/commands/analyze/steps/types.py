"""Shared types passed between pipeline steps.

Types used by both REST and GraphQL analysis pipelines live here.
REST-specific types are in ``steps.rest.types``; GraphQL-specific
types will be in ``steps.graphql.types``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cli.commands.capture.types import Context, Trace, WsMessage

# -- Auth types (shared across protocols) ------------------------------------


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


# -- Correlation (UI context <-> API traces) ---------------------------------


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


# -- Inputs for shared mechanical steps -------------------------------------


@dataclass
class TracesWithBaseUrl:
    """Traces to filter, together with the detected base URL."""

    traces: list[Trace]
    base_url: str


# -- Branch abstraction (protocol-agnostic pipeline) -------------------------


@dataclass
class BranchContext:
    """Shared context passed to each protocol branch."""

    base_url: str
    app_name: str
    source_filename: str
    correlations: list[Correlation]
    all_filtered_traces: list[Trace]
    skip_enrich: bool
    on_progress: Callable[[str], None]
    auth_task: asyncio.Task[AuthInfo]


@dataclass
class BranchOutput:
    """Result produced by a single protocol branch."""

    protocol: str
    artifact: Any
    file_extension: str
    label: str


# -- Pipeline result ----------------------------------------------------------


@dataclass
class AnalysisResult:
    """Result of the analysis pipeline, supporting any combination of protocols."""

    outputs: list[BranchOutput] = field(default_factory=lambda: list[BranchOutput]())
    auth: AuthInfo | None = None
    base_url: str = ""
    auth_helper_script: str | None = None
