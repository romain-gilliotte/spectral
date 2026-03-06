"""Internal dataclasses and Pydantic response models for MCP pipeline steps."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from cli.commands.capture.types import Context, Trace
from cli.formats.mcp_tool import ToolDefinition


class IdentifyResponse(BaseModel):
    """LLM response for the identify capabilities step."""

    useful: bool
    name: str | None = None
    description: str | None = None


class BuildToolResponse(BaseModel):
    """LLM response for the build tool step."""

    tool: ToolDefinition
    consumed_trace_ids: list[str]


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
    contexts: list[Context]
    base_url: str
    existing_tools: list[ToolDefinition]
    system_context: str


@dataclass
class ToolBuildResult:
    """Output of the BuildToolStep: tool definition + consumed trace IDs."""

    tool: ToolDefinition
    consumed_trace_ids: list[str]


@dataclass
class IdentifyInput:
    """Input for the IdentifyCapabilitiesStep (per-trace evaluation)."""

    remaining_traces: list[Trace]
    base_url: str
    target_trace: Trace
    existing_tools: list[ToolDefinition]
    system_context: str


@dataclass
class McpPipelineResult:
    """Result of the MCP analysis pipeline."""

    tools: list[ToolDefinition] = field(
        default_factory=lambda: list[ToolDefinition]()
    )
    base_url: str = ""
