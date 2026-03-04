"""Internal dataclasses for MCP pipeline steps."""

from __future__ import annotations

from dataclasses import dataclass, field

from cli.commands.analyze.steps.types import AuthInfo, Correlation
from cli.commands.capture.types import Trace
from cli.formats.mcp_tool import ToolDefinition


@dataclass
class ToolCandidate:
    """A proposed tool before full definition is built."""

    name: str
    description: str
    trace_ids: list[str]


@dataclass
class ToolBuildInput:
    """Input for the BuildToolStep."""

    candidate: ToolCandidate
    traces: list[Trace]
    base_url: str
    existing_tools: list[ToolDefinition]


@dataclass
class IdentifyInput:
    """Input for the IdentifyCapabilitiesStep."""

    correlations: list[Correlation]
    remaining_traces: list[Trace]
    base_url: str


@dataclass
class CleanupInput:
    """Input for the CleanupTracesStep."""

    traces: list[Trace]
    tool_definition: ToolDefinition
    base_url: str


@dataclass
class McpPipelineResult:
    """Result of the MCP analysis pipeline."""

    tools: list[ToolDefinition] = field(
        default_factory=lambda: list[ToolDefinition]()
    )
    base_url: str = ""
    auth: AuthInfo | None = None
    auth_acquire_script: str | None = None
