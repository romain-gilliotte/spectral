"""In-memory data classes for loaded capture bundles.

These wrap the Pydantic metadata models with their associated binary payloads,
providing convenient access to all data from a loaded capture bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import uuid

from cli.formats.capture_bundle import (
    CaptureManifest,
    CaptureStats,
    ContextMeta,
    Timeline,
    TimelineEvent,
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
class WsMessage:
    """A single WebSocket message with its payload."""

    meta: WsMessageMeta
    payload: bytes = b""


@dataclass
class WsConnection:
    """A WebSocket connection with all its messages."""

    meta: WsConnectionMeta
    messages: list[WsMessage] = field(default_factory=lambda: list[WsMessage]())


@dataclass
class Context:
    """A UI context snapshot."""

    meta: ContextMeta


@dataclass
class CaptureBundle:
    """A fully loaded capture bundle with all data in memory."""

    manifest: CaptureManifest
    traces: list[Trace] = field(default_factory=lambda: list[Trace]())
    ws_connections: list[WsConnection] = field(
        default_factory=lambda: list[WsConnection]()
    )
    contexts: list[Context] = field(default_factory=lambda: list[Context]())
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


# ---------------------------------------------------------------------------
# Bundle merging
# ---------------------------------------------------------------------------

# Matches IDs like t_0001, c_0003, ws_0001, ws_0001_m002
_ID_RE = re.compile(r"^(t|c|ws)(_\d{4}(?:_m\d{3})?)$")


def _prefix_id(raw_id: str, capture_idx: int) -> str:
    """Insert a 3-digit capture index after the type prefix.

    ``t_0001`` with index 2 → ``t_002_0001``
    ``ws_0001_m002`` with index 3 → ``ws_003_0001_m002``
    """
    m = _ID_RE.match(raw_id)
    if not m:
        return raw_id  # pragma: no cover — defensive
    prefix = m.group(1)       # t, c, ws
    suffix = m.group(2)       # _0001 or _0001_m002
    return f"{prefix}_{capture_idx:03d}{suffix}"


def _build_id_map(bundle: CaptureBundle, capture_idx: int) -> dict[str, str]:
    """Build old→new ID mapping for all items in a bundle."""
    mapping: dict[str, str] = {}
    for t in bundle.traces:
        mapping[t.meta.id] = _prefix_id(t.meta.id, capture_idx)
    for c in bundle.contexts:
        mapping[c.meta.id] = _prefix_id(c.meta.id, capture_idx)
    for ws in bundle.ws_connections:
        mapping[ws.meta.id] = _prefix_id(ws.meta.id, capture_idx)
        for msg in ws.messages:
            mapping[msg.meta.id] = _prefix_id(msg.meta.id, capture_idx)
    return mapping


def _remap_trace(trace: Trace, mapping: dict[str, str]) -> Trace:
    """Return a new Trace with remapped IDs and cross-references."""
    new_id = mapping[trace.meta.id]
    old_id = trace.meta.id

    req = trace.meta.request.model_copy()
    if req.body_file:
        req.body_file = req.body_file.replace(old_id, new_id)

    resp = trace.meta.response.model_copy()
    if resp.body_file:
        resp.body_file = resp.body_file.replace(old_id, new_id)

    new_meta = trace.meta.model_copy(update={
        "id": new_id,
        "request": req,
        "response": resp,
        "context_refs": [mapping.get(r, r) for r in trace.meta.context_refs],
    })
    return Trace(meta=new_meta, request_body=trace.request_body, response_body=trace.response_body)


def _remap_context(ctx: Context, mapping: dict[str, str]) -> Context:
    """Return a new Context with a remapped ID."""
    new_meta = ctx.meta.model_copy(update={"id": mapping[ctx.meta.id]})
    return Context(meta=new_meta)


def _remap_ws_connection(ws: WsConnection, mapping: dict[str, str]) -> WsConnection:
    """Return a new WsConnection with remapped IDs and messages."""
    new_ws_id = mapping[ws.meta.id]
    new_handshake_ref = (
        mapping.get(ws.meta.handshake_trace_ref, ws.meta.handshake_trace_ref)
        if ws.meta.handshake_trace_ref
        else None
    )
    new_meta = ws.meta.model_copy(update={
        "id": new_ws_id,
        "handshake_trace_ref": new_handshake_ref,
        "context_refs": [mapping.get(r, r) for r in ws.meta.context_refs],
    })
    new_messages: list[WsMessage] = []
    for msg in ws.messages:
        new_msg_id = mapping[msg.meta.id]
        old_msg_id = msg.meta.id

        new_payload_file = msg.meta.payload_file
        if new_payload_file:
            new_payload_file = new_payload_file.replace(old_msg_id, new_msg_id)

        new_msg_meta = msg.meta.model_copy(update={
            "id": new_msg_id,
            "connection_ref": new_ws_id,
            "payload_file": new_payload_file,
            "context_refs": [mapping.get(r, r) for r in msg.meta.context_refs],
        })
        new_messages.append(WsMessage(meta=new_msg_meta, payload=msg.payload))
    return WsConnection(meta=new_meta, messages=new_messages)


def merge_bundles(bundles: list[CaptureBundle]) -> CaptureBundle:
    """Merge multiple capture bundles into a single transient bundle.

    If *bundles* has a single element, it is returned as-is (no renaming).
    For N > 1 captures, IDs are prefixed with a 3-digit capture index to
    avoid collisions (e.g. ``t_0001`` from capture 2 → ``t_002_0001``).

    Raises ``ValueError`` if *bundles* is empty.
    """
    if not bundles:
        raise ValueError("Cannot merge an empty list of bundles")
    if len(bundles) == 1:
        return bundles[0]

    all_traces: list[Trace] = []
    all_contexts: list[Context] = []
    all_ws: list[WsConnection] = []
    all_timeline: list[TimelineEvent] = []

    total_stats = CaptureStats()

    for idx, bundle in enumerate(bundles, start=1):
        mapping = _build_id_map(bundle, idx)

        all_traces.extend(_remap_trace(t, mapping) for t in bundle.traces)
        all_contexts.extend(_remap_context(c, mapping) for c in bundle.contexts)
        all_ws.extend(_remap_ws_connection(ws, mapping) for ws in bundle.ws_connections)

        for ev in bundle.timeline.events:
            all_timeline.append(TimelineEvent(
                timestamp=ev.timestamp,
                type=ev.type,
                ref=mapping.get(ev.ref, ev.ref),
            ))

        total_stats.trace_count += bundle.manifest.stats.trace_count
        total_stats.ws_connection_count += bundle.manifest.stats.ws_connection_count
        total_stats.ws_message_count += bundle.manifest.stats.ws_message_count
        total_stats.context_count += bundle.manifest.stats.context_count

    # Sort timeline by timestamp
    all_timeline.sort(key=lambda e: e.timestamp)

    # Synthetic manifest from first bundle
    first = bundles[0].manifest
    # Earliest created_at
    earliest = min(b.manifest.created_at for b in bundles)

    manifest = CaptureManifest(
        capture_id=str(uuid.uuid4()),
        created_at=earliest,
        app=first.app.model_copy(),
        browser=first.browser.model_copy() if first.browser else None,
        extension_version=first.extension_version,
        duration_ms=sum(b.manifest.duration_ms for b in bundles),
        stats=total_stats,
        capture_method="merged",
    )

    return CaptureBundle(
        manifest=manifest,
        traces=all_traces,
        ws_connections=all_ws,
        contexts=all_contexts,
        timeline=Timeline(events=all_timeline),
    )
