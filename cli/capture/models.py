"""In-memory data classes for loaded capture bundles.

These wrap the Pydantic metadata models with their associated binary payloads,
providing convenient access to all data from a loaded capture bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cli.formats.capture_bundle import (
    CaptureManifest,
    ContextMeta,
    Timeline,
    TraceMeta,
    WsConnectionMeta,
    WsMessageMeta,
)


@dataclass
class Trace:
    """An HTTP trace with its request/response bodies loaded into memory."""

    meta: TraceMeta
    request_body: bytes = b""
    response_body: bytes = b""


@dataclass
class WsConnection:
    """A WebSocket connection with all its messages."""

    meta: WsConnectionMeta
    messages: list[WsMessage] = field(default_factory=list)


@dataclass
class WsMessage:
    """A single WebSocket message with its payload."""

    meta: WsMessageMeta
    payload: bytes = b""


@dataclass
class Context:
    """A UI context snapshot."""

    meta: ContextMeta


@dataclass
class CaptureBundle:
    """A fully loaded capture bundle with all data in memory."""

    manifest: CaptureManifest
    traces: list[Trace] = field(default_factory=list)
    ws_connections: list[WsConnection] = field(default_factory=list)
    contexts: list[Context] = field(default_factory=list)
    timeline: Timeline = field(default_factory=Timeline)

    def get_trace(self, trace_id: str) -> Trace | None:
        for t in self.traces:
            if t.meta.id == trace_id:
                return t
        return None

    def get_context(self, context_id: str) -> Context | None:
        for c in self.contexts:
            if c.meta.id == context_id:
                return c
        return None

    def get_ws_connection(self, ws_id: str) -> WsConnection | None:
        for ws in self.ws_connections:
            if ws.meta.id == ws_id:
                return ws
        return None
