"""Tests for capture bundle types and merge_bundles."""

from __future__ import annotations

import json

import pytest

from cli.commands.capture.types import (
    CaptureBundle,
    WsConnection,
    WsMessage,
    merge_bundles,
)
from cli.formats.capture_bundle import (
    AppInfo,
    BrowserInfo,
    CaptureManifest,
    CaptureStats,
    Timeline,
    TimelineEvent,
)
from tests.conftest import make_context, make_trace, make_ws_connection, make_ws_message


def _make_bundle(
    capture_id: str,
    created_at: str = "2026-02-13T15:30:00Z",
    trace_ids: list[str] | None = None,
    context_ids: list[str] | None = None,
    ws_id: str | None = None,
    ws_msg_ids: list[str] | None = None,
    base_timestamp: int = 1000000,
) -> CaptureBundle:
    """Helper to build a small bundle for merge tests."""
    trace_ids = trace_ids or ["t_0001"]
    context_ids = context_ids or ["c_0001"]

    traces = [
        make_trace(
            tid, "GET", f"https://api.example.com/api/{tid}",
            200, base_timestamp + i * 1000,
            response_body=json.dumps({"id": tid}).encode(),
            context_refs=[context_ids[0]] if context_ids else [],
        )
        for i, tid in enumerate(trace_ids)
    ]
    contexts = [
        make_context(cid, base_timestamp - 500 + i * 1000)
        for i, cid in enumerate(context_ids)
    ]

    events: list[TimelineEvent] = []
    for ctx in contexts:
        events.append(TimelineEvent(timestamp=ctx.meta.timestamp, type="context", ref=ctx.meta.id))
    for tr in traces:
        events.append(TimelineEvent(timestamp=tr.meta.timestamp, type="trace", ref=tr.meta.id))

    ws_connections: list[WsConnection] = []
    if ws_id:
        msgs: list[WsMessage] = []
        for mid in (ws_msg_ids or []):
            msg = make_ws_message(mid, ws_id, base_timestamp + 500, "send", b'{"ping":1}')
            msgs.append(msg)
            events.append(TimelineEvent(timestamp=msg.meta.timestamp, type="ws_message", ref=mid))
        ws_conn = make_ws_connection(ws_id, "wss://ws.example.com/ws", base_timestamp, messages=msgs)
        ws_connections.append(ws_conn)
        events.append(TimelineEvent(timestamp=base_timestamp, type="ws_open", ref=ws_id))

    events.sort(key=lambda e: e.timestamp)

    manifest = CaptureManifest(
        capture_id=capture_id,
        created_at=created_at,
        app=AppInfo(name="Test App", base_url="https://example.com", title="Test"),
        browser=BrowserInfo(name="Chrome", version="133.0"),
        duration_ms=5000,
        stats=CaptureStats(
            trace_count=len(traces),
            ws_connection_count=len(ws_connections),
            ws_message_count=sum(len(ws.messages) for ws in ws_connections),
            context_count=len(contexts),
        ),
    )

    return CaptureBundle(
        manifest=manifest,
        traces=traces,
        ws_connections=ws_connections,
        contexts=contexts,
        timeline=Timeline(events=events),
    )


class TestMergeBundles:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            merge_bundles([])

    def test_single_returns_same(self) -> None:
        bundle = _make_bundle("cap-1")
        result = merge_bundles([bundle])
        assert result is bundle

    def test_two_bundles_traces_concatenated(self) -> None:
        b1 = _make_bundle("cap-1", trace_ids=["t_0001", "t_0002"], context_ids=["c_0001"])
        b2 = _make_bundle("cap-2", trace_ids=["t_0001"], context_ids=["c_0001"], base_timestamp=2000000)

        merged = merge_bundles([b1, b2])

        assert len(merged.traces) == 3
        trace_ids = {t.meta.id for t in merged.traces}
        assert trace_ids == {"t_001_0001", "t_001_0002", "t_002_0001"}

    def test_two_bundles_contexts_concatenated(self) -> None:
        b1 = _make_bundle("cap-1", context_ids=["c_0001"])
        b2 = _make_bundle("cap-2", context_ids=["c_0001", "c_0002"], base_timestamp=2000000)

        merged = merge_bundles([b1, b2])

        assert len(merged.contexts) == 3
        ctx_ids = {c.meta.id for c in merged.contexts}
        assert ctx_ids == {"c_001_0001", "c_002_0001", "c_002_0002"}

    def test_two_bundles_ws_concatenated(self) -> None:
        b1 = _make_bundle("cap-1", ws_id="ws_0001", ws_msg_ids=["ws_0001_m001"])
        b2 = _make_bundle("cap-2", ws_id="ws_0001", ws_msg_ids=["ws_0001_m001", "ws_0001_m002"], base_timestamp=2000000)

        merged = merge_bundles([b1, b2])

        assert len(merged.ws_connections) == 2
        ws_ids = {ws.meta.id for ws in merged.ws_connections}
        assert ws_ids == {"ws_001_0001", "ws_002_0001"}

        # Messages remapped
        ws1 = next(ws for ws in merged.ws_connections if ws.meta.id == "ws_001_0001")
        assert len(ws1.messages) == 1
        assert ws1.messages[0].meta.id == "ws_001_0001_m001"
        assert ws1.messages[0].meta.connection_ref == "ws_001_0001"

        ws2 = next(ws for ws in merged.ws_connections if ws.meta.id == "ws_002_0001")
        assert len(ws2.messages) == 2
        msg_ids = {m.meta.id for m in ws2.messages}
        assert msg_ids == {"ws_002_0001_m001", "ws_002_0001_m002"}

    def test_handshake_trace_ref_remapped(self) -> None:
        b1 = _make_bundle("cap-1", trace_ids=["t_0001"], ws_id="ws_0001", ws_msg_ids=[])
        b2 = _make_bundle("cap-2", trace_ids=["t_0001"], ws_id="ws_0001", ws_msg_ids=[], base_timestamp=2000000)

        # Set handshake_trace_ref pointing to a trace
        b1.ws_connections[0].meta.handshake_trace_ref = "t_0001"
        b2.ws_connections[0].meta.handshake_trace_ref = "t_0001"

        merged = merge_bundles([b1, b2])

        ws1 = next(ws for ws in merged.ws_connections if ws.meta.id == "ws_001_0001")
        assert ws1.meta.handshake_trace_ref == "t_001_0001"

        ws2 = next(ws for ws in merged.ws_connections if ws.meta.id == "ws_002_0001")
        assert ws2.meta.handshake_trace_ref == "t_002_0001"

    def test_handshake_trace_ref_none_preserved(self) -> None:
        b1 = _make_bundle("cap-1", ws_id="ws_0001", ws_msg_ids=[])
        b2 = _make_bundle("cap-2", ws_id="ws_0001", ws_msg_ids=[], base_timestamp=2000000)

        merged = merge_bundles([b1, b2])

        for ws in merged.ws_connections:
            assert ws.meta.handshake_trace_ref is None

    def test_context_refs_remapped(self) -> None:
        b1 = _make_bundle("cap-1", trace_ids=["t_0001"], context_ids=["c_0001"])
        b2 = _make_bundle("cap-2", trace_ids=["t_0001"], context_ids=["c_0001"], base_timestamp=2000000)

        merged = merge_bundles([b1, b2])

        t1 = next(t for t in merged.traces if t.meta.id == "t_001_0001")
        assert t1.meta.context_refs == ["c_001_0001"]

        t2 = next(t for t in merged.traces if t.meta.id == "t_002_0001")
        assert t2.meta.context_refs == ["c_002_0001"]

    def test_body_files_remapped(self) -> None:
        b1 = _make_bundle("cap-1", trace_ids=["t_0001"])
        b2 = _make_bundle("cap-2", trace_ids=["t_0001"], base_timestamp=2000000)

        merged = merge_bundles([b1, b2])

        t1 = next(t for t in merged.traces if t.meta.id == "t_001_0001")
        assert t1.meta.response.body_file == "t_001_0001_response.bin"

        t2 = next(t for t in merged.traces if t.meta.id == "t_002_0001")
        assert t2.meta.response.body_file == "t_002_0001_response.bin"

    def test_timeline_sorted(self) -> None:
        b1 = _make_bundle("cap-1", trace_ids=["t_0001"], context_ids=["c_0001"], base_timestamp=3000000)
        b2 = _make_bundle("cap-2", trace_ids=["t_0001"], context_ids=["c_0001"], base_timestamp=1000000)

        merged = merge_bundles([b1, b2])

        timestamps = [e.timestamp for e in merged.timeline.events]
        assert timestamps == sorted(timestamps)

    def test_timeline_refs_remapped(self) -> None:
        b1 = _make_bundle("cap-1", trace_ids=["t_0001"], context_ids=["c_0001"])
        b2 = _make_bundle("cap-2", trace_ids=["t_0001"], context_ids=["c_0001"], base_timestamp=2000000)

        merged = merge_bundles([b1, b2])

        refs = {e.ref for e in merged.timeline.events}
        assert "t_0001" not in refs
        assert "c_0001" not in refs
        assert "t_001_0001" in refs
        assert "t_002_0001" in refs
        assert "c_001_0001" in refs
        assert "c_002_0001" in refs

    def test_stats_summed(self) -> None:
        b1 = _make_bundle("cap-1", trace_ids=["t_0001", "t_0002"], context_ids=["c_0001"])
        b2 = _make_bundle("cap-2", trace_ids=["t_0001"], context_ids=["c_0001", "c_0002"], base_timestamp=2000000)

        merged = merge_bundles([b1, b2])

        assert merged.manifest.stats.trace_count == 3
        assert merged.manifest.stats.context_count == 3

    def test_manifest_synthetic(self) -> None:
        b1 = _make_bundle("cap-1", created_at="2026-02-15T10:00:00Z")
        b2 = _make_bundle("cap-2", created_at="2026-02-13T08:00:00Z", base_timestamp=2000000)

        merged = merge_bundles([b1, b2])

        assert merged.manifest.capture_method == "merged"
        assert merged.manifest.created_at == "2026-02-13T08:00:00Z"
        assert merged.manifest.capture_id != "cap-1"
        assert merged.manifest.capture_id != "cap-2"
        assert merged.manifest.app.name == "Test App"
