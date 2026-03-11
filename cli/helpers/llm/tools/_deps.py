"""Tool dependencies for PydanticAI RunContext injection."""

from __future__ import annotations

from dataclasses import dataclass, field

from cli.commands.capture.types import Context, Trace


@dataclass
class ToolDeps:
    """Dependencies injected into tools via ``RunContext``."""

    traces: list[Trace] = field(default_factory=lambda: list[Trace]())
    contexts: list[Context] = field(default_factory=lambda: list[Context]())
    trace_index: dict[str, Trace] = field(default_factory=lambda: dict[str, Trace](), init=False)
    context_index: dict[str, Context] = field(default_factory=lambda: dict[str, Context](), init=False)

    def __post_init__(self) -> None:
        self.trace_index = {t.meta.id: t for t in self.traces}
        self.context_index = {c.meta.id: c for c in self.contexts}
