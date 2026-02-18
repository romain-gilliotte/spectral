"""Tests for capture bundle loader/writer."""

from pathlib import Path

from cli.capture.loader import (
    load_bundle,
    load_bundle_bytes,
    write_bundle,
    write_bundle_bytes,
)
from cli.capture.models import CaptureBundle


class TestBundleRoundtrip:
    def test_write_and_load_bytes(self, sample_bundle: CaptureBundle) -> None:
        """Test writing a bundle to bytes and loading it back."""
        data = write_bundle_bytes(sample_bundle)
        loaded = load_bundle_bytes(data)

        assert loaded.manifest.capture_id == sample_bundle.manifest.capture_id
        assert loaded.manifest.app.name == "Test App"
        assert len(loaded.traces) == len(sample_bundle.traces)
        assert len(loaded.ws_connections) == len(sample_bundle.ws_connections)
        assert len(loaded.contexts) == len(sample_bundle.contexts)
        assert len(loaded.timeline.events) == len(sample_bundle.timeline.events)

    def test_write_and_load_file(
        self, sample_bundle: CaptureBundle, tmp_path: Path
    ) -> None:
        """Test writing a bundle to disk and loading it back."""
        path = tmp_path / "test_capture.zip"
        write_bundle(sample_bundle, path)

        assert path.exists()
        loaded = load_bundle(path)

        assert loaded.manifest.capture_id == sample_bundle.manifest.capture_id
        assert len(loaded.traces) == len(sample_bundle.traces)

    def test_trace_bodies_preserved(self, sample_bundle: CaptureBundle) -> None:
        """Test that request/response bodies survive roundtrip."""
        data = write_bundle_bytes(sample_bundle)
        loaded = load_bundle_bytes(data)

        for orig, loaded_trace in zip(sample_bundle.traces, loaded.traces):
            assert loaded_trace.request_body == orig.request_body
            assert loaded_trace.response_body == orig.response_body

    def test_ws_messages_preserved(self, sample_bundle: CaptureBundle) -> None:
        """Test that WebSocket messages survive roundtrip."""
        data = write_bundle_bytes(sample_bundle)
        loaded = load_bundle_bytes(data)

        assert len(loaded.ws_connections) == 1
        ws = loaded.ws_connections[0]
        assert ws.meta.id == "ws_0001"
        assert ws.meta.url == "wss://realtime.example.com/ws"
        assert len(ws.messages) == 2
        assert ws.messages[0].payload == b'{"type":"subscribe","id":"1"}'

    def test_context_preserved(self, sample_bundle: CaptureBundle) -> None:
        """Test that contexts survive roundtrip."""
        data = write_bundle_bytes(sample_bundle)
        loaded = load_bundle_bytes(data)

        assert len(loaded.contexts) == 2
        assert loaded.contexts[0].meta.action == "click"
        assert loaded.contexts[0].meta.element.text == "Users"

    def test_timeline_preserved(self, sample_bundle: CaptureBundle) -> None:
        """Test that timeline survives roundtrip."""
        data = write_bundle_bytes(sample_bundle)
        loaded = load_bundle_bytes(data)

        assert len(loaded.timeline.events) == 9
        assert loaded.timeline.events[0].type == "context"
        assert loaded.timeline.events[1].type == "trace"

    def test_empty_bundle(self):
        """Test roundtrip of an empty bundle."""
        from cli.formats.capture_bundle import (
            AppInfo,
            BrowserInfo,
            CaptureManifest,
            CaptureStats,
        )

        bundle = CaptureBundle(
            manifest=CaptureManifest(
                capture_id="empty",
                created_at="2026-01-01T00:00:00Z",
                app=AppInfo(name="Empty", base_url="http://localhost", title="Empty"),
                browser=BrowserInfo(name="Chrome", version="1.0"),
                duration_ms=0,
                stats=CaptureStats(),
            ),
        )
        data = write_bundle_bytes(bundle)
        loaded = load_bundle_bytes(data)
        assert loaded.manifest.capture_id == "empty"
        assert len(loaded.traces) == 0
        assert len(loaded.ws_connections) == 0
        assert len(loaded.contexts) == 0

    def test_binary_body_roundtrip(self):
        """Test that binary (non-UTF-8) bodies survive roundtrip."""
        from cli.formats.capture_bundle import (
            AppInfo,
            BrowserInfo,
            CaptureManifest,
            CaptureStats,
        )
        from tests.conftest import make_trace

        binary_body = bytes(range(256))  # All byte values
        trace = make_trace(
            "t_0001",
            "POST",
            "http://localhost/binary",
            200,
            timestamp=1000,
            request_body=binary_body,
            response_body=binary_body,
        )

        bundle = CaptureBundle(
            manifest=CaptureManifest(
                capture_id="binary",
                created_at="2026-01-01T00:00:00Z",
                app=AppInfo(name="Bin", base_url="http://localhost", title="Bin"),
                browser=BrowserInfo(name="Chrome", version="1.0"),
                duration_ms=0,
                stats=CaptureStats(trace_count=1),
            ),
            traces=[trace],
        )
        data = write_bundle_bytes(bundle)
        loaded = load_bundle_bytes(data)
        assert loaded.traces[0].request_body == binary_body
        assert loaded.traces[0].response_body == binary_body


class TestBundleLookups:
    def test_get_trace(self, sample_bundle: CaptureBundle) -> None:
        trace = sample_bundle.get_trace("t_0001")
        assert trace is not None
        assert trace.meta.request.method == "GET"

    def test_get_trace_not_found(self, sample_bundle: CaptureBundle) -> None:
        assert sample_bundle.get_trace("nonexistent") is None

    def test_get_context(self, sample_bundle: CaptureBundle) -> None:
        ctx = sample_bundle.get_context("c_0001")
        assert ctx is not None
        assert ctx.meta.action == "click"

    def test_get_context_not_found(self, sample_bundle: CaptureBundle) -> None:
        assert sample_bundle.get_context("nonexistent") is None

    def test_get_ws_connection(self, sample_bundle: CaptureBundle) -> None:
        ws = sample_bundle.get_ws_connection("ws_0001")
        assert ws is not None
        assert ws.meta.url == "wss://realtime.example.com/ws"

    def test_get_ws_connection_not_found(self, sample_bundle: CaptureBundle) -> None:
        assert sample_bundle.get_ws_connection("nonexistent") is None
