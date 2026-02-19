"""Tests for the generic capture proxy engine (cli/capture/proxy.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cli.commands.capture.loader import load_bundle_bytes, write_bundle_bytes
from cli.commands.capture.proxy import (
    CaptureAddon,
    DiscoveryAddon,
    flow_to_trace,
    ws_flow_to_connection,
)
from cli.commands.capture.types import WsMessage
from cli.formats.capture_bundle import WsMessageMeta


def _make_mock_flow(
    method: str = "GET",
    url: str = "https://api.example.com/data",
    status: int = 200,
    req_body: bytes = b"",
    resp_body: bytes = b'{"ok": true}',
    req_headers: dict[str, str] | None = None,
    resp_headers: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock mitmproxy HTTPFlow."""
    flow = MagicMock()
    flow.request.method = method
    flow.request.pretty_url = url
    flow.request.host = "api.example.com"
    flow.request.content = req_body
    flow.request.timestamp_start = 1700000000.0
    flow.request.headers = MagicMock()
    flow.request.headers.items = MagicMock(
        return_value=list((req_headers or {}).items())
    )
    flow.request.headers.get = MagicMock(return_value="")

    flow.response = MagicMock()
    flow.response.status_code = status
    flow.response.reason = "OK"
    flow.response.content = resp_body
    flow.response.timestamp_end = 1700000000.15
    flow.response.headers = MagicMock()
    flow.response.headers.items = MagicMock(
        return_value=list(
            (resp_headers or {"Content-Type": "application/json"}).items()
        )
    )

    flow.websocket = None
    return flow


class TestFlowToTrace:
    def test_basic_conversion(self) -> None:
        flow = _make_mock_flow()
        trace = flow_to_trace(flow, "t_0001")

        assert trace.meta.id == "t_0001"
        assert trace.meta.request.method == "GET"
        assert trace.meta.request.url == "https://api.example.com/data"
        assert trace.meta.response.status == 200
        assert trace.response_body == b'{"ok": true}'
        assert trace.meta.timing.total_ms == pytest.approx(150.0, abs=1.0)  # pyright: ignore[reportUnknownMemberType]

    def test_post_with_body(self) -> None:
        flow = _make_mock_flow(
            method="POST",
            req_body=b'{"name": "test"}',
            req_headers={"Content-Type": "application/json"},
        )
        trace = flow_to_trace(flow, "t_0002")

        assert trace.meta.request.method == "POST"
        assert trace.request_body == b'{"name": "test"}'
        assert trace.meta.request.body_file == "t_0002_request.bin"
        assert trace.meta.request.body_size == len(b'{"name": "test"}')

    def test_no_response_body(self) -> None:
        flow = _make_mock_flow(status=204, resp_body=b"")
        trace = flow_to_trace(flow, "t_0003")

        assert trace.meta.response.status == 204
        assert trace.response_body == b""
        assert trace.meta.response.body_file is None

    def test_headers_mapped(self) -> None:
        flow = _make_mock_flow(
            req_headers={
                "Authorization": "Bearer tok123",
                "Accept": "application/json",
            },
            resp_headers={"Content-Type": "application/json", "X-Request-Id": "abc"},
        )
        trace = flow_to_trace(flow, "t_0004")

        assert len(trace.meta.request.headers) == 2
        assert len(trace.meta.response.headers) == 2

    def test_initiator_is_proxy(self) -> None:
        flow = _make_mock_flow()
        trace = flow_to_trace(flow, "t_0005")
        assert trace.meta.initiator.type == "proxy"


class TestCaptureAddon:
    def test_response_adds_trace(self) -> None:
        addon = CaptureAddon()
        flow = _make_mock_flow()
        addon.response(flow)

        assert len(addon.traces) == 1
        assert addon.traces[0].meta.id == "t_0001"
        assert "api.example.com" in addon.domains_seen

    def test_multiple_responses_increment_counter(self) -> None:
        addon = CaptureAddon()
        for _ in range(3):
            addon.response(_make_mock_flow())

        assert len(addon.traces) == 3
        assert [t.meta.id for t in addon.traces] == ["t_0001", "t_0002", "t_0003"]

    def test_websocket_flow_skipped_in_response(self) -> None:
        addon = CaptureAddon()
        flow = _make_mock_flow()
        flow.websocket = MagicMock()  # Mark as WS flow
        addon.response(flow)

        assert len(addon.traces) == 0

    def test_build_bundle(self) -> None:
        addon = CaptureAddon()
        addon.response(_make_mock_flow())
        addon.response(_make_mock_flow(url="https://api.example.com/users"))

        bundle = addon.build_bundle("Test App", 1700000000.0, 1700000010.0)

        assert bundle.manifest.capture_method == "proxy"
        assert bundle.manifest.browser is None
        assert bundle.manifest.extension_version is None
        assert bundle.manifest.app.name == "Test App"
        assert bundle.manifest.stats.trace_count == 2
        assert bundle.manifest.stats.context_count == 0
        assert bundle.manifest.duration_ms == 10000
        assert len(bundle.traces) == 2
        assert len(bundle.contexts) == 0
        assert len(bundle.timeline.events) == 2

    def test_build_bundle_roundtrip(self) -> None:
        """Verify that the bundle produced by the addon can be written and loaded."""
        addon = CaptureAddon()
        addon.response(_make_mock_flow())

        bundle = addon.build_bundle("Test App", 1700000000.0, 1700000005.0)

        data = write_bundle_bytes(bundle)
        loaded = load_bundle_bytes(data)

        assert loaded.manifest.capture_method == "proxy"
        assert loaded.manifest.browser is None
        assert len(loaded.traces) == 1
        assert loaded.traces[0].meta.request.method == "GET"
        assert loaded.traces[0].response_body == b'{"ok": true}'


class TestWsFlowToConnection:
    def test_basic_ws_connection(self) -> None:
        flow = MagicMock()
        flow.request.pretty_url = "wss://ws.example.com/socket"
        flow.request.timestamp_start = 1700000000.0
        flow.request.headers.get = MagicMock(return_value="graphql-ws")

        conn = ws_flow_to_connection(flow, "ws_0001", [])

        assert conn.meta.id == "ws_0001"
        assert conn.meta.url == "wss://ws.example.com/socket"
        assert conn.meta.protocols == ["graphql-ws"]
        assert conn.meta.message_count == 0

    def test_ws_with_messages(self) -> None:
        flow = MagicMock()
        flow.request.pretty_url = "wss://ws.example.com/socket"
        flow.request.timestamp_start = 1700000000.0
        flow.request.headers.get = MagicMock(return_value="")

        msg = WsMessage(
            meta=WsMessageMeta(
                id="ws_0001_m001",
                connection_ref="ws_0001",
                timestamp=1700000001000,
                direction="send",
                opcode="text",
                payload_file="ws_0001_m001.bin",
                payload_size=5,
            ),
            payload=b"hello",
        )
        conn = ws_flow_to_connection(flow, "ws_0001", [msg])

        assert conn.meta.message_count == 1
        assert len(conn.messages) == 1


class TestDiscoveryAddon:
    def test_tls_clienthello_logs_domain(self) -> None:
        addon = DiscoveryAddon()
        data = MagicMock()
        data.context.client.sni = "api.example.com"
        data.ignore_connection = False

        addon.tls_clienthello(data)

        assert addon.domains == {"api.example.com": 1}
        assert data.ignore_connection is True

    def test_multiple_domains_counted(self) -> None:
        addon = DiscoveryAddon()

        for _ in range(3):
            data = MagicMock()
            data.context.client.sni = "api.example.com"
            addon.tls_clienthello(data)

        data2 = MagicMock()
        data2.context.client.sni = "cdn.example.com"
        addon.tls_clienthello(data2)

        assert addon.domains["api.example.com"] == 3
        assert addon.domains["cdn.example.com"] == 1

    def test_plain_http_request_logged(self) -> None:
        addon = DiscoveryAddon()
        flow = MagicMock()
        flow.request.host = "http.example.com"

        addon.request(flow)

        assert addon.domains == {"http.example.com": 1}

    def test_empty_sni_skipped(self) -> None:
        addon = DiscoveryAddon()
        data = MagicMock()
        data.context.client.sni = ""

        addon.tls_clienthello(data)

        assert addon.domains == {}
        assert data.ignore_connection is True


class TestManifestCompat:
    def test_existing_manifests_still_parse(self) -> None:
        """Chrome extension bundles without capture_method should still work."""
        from cli.formats.capture_bundle import (
            AppInfo,
            BrowserInfo,
            CaptureManifest,
            CaptureStats,
        )

        manifest = CaptureManifest(
            capture_id="test",
            created_at="2026-01-01T00:00:00Z",
            app=AppInfo(name="Test", base_url="https://test.com", title="Test"),
            browser=BrowserInfo(name="Chrome", version="133.0"),
            duration_ms=1000,
            stats=CaptureStats(),
        )
        assert manifest.capture_method == "chrome_extension"
        assert manifest.browser is not None
        assert manifest.extension_version == "0.1.0"

    def test_proxy_manifest_no_browser(self) -> None:
        from cli.formats.capture_bundle import (
            AppInfo,
            CaptureManifest,
            CaptureStats,
        )

        manifest = CaptureManifest(
            capture_id="test",
            created_at="2026-01-01T00:00:00Z",
            app=AppInfo(
                name="Android App", base_url="https://api.app.com", title="App"
            ),
            browser=None,
            extension_version=None,
            duration_ms=5000,
            stats=CaptureStats(trace_count=10),
            capture_method="proxy",
        )
        assert manifest.browser is None
        assert manifest.extension_version is None
        assert manifest.capture_method == "proxy"

    def test_manifest_json_roundtrip_without_browser(self) -> None:
        from cli.formats.capture_bundle import (
            AppInfo,
            CaptureManifest,
            CaptureStats,
        )

        manifest = CaptureManifest(
            capture_id="test",
            created_at="2026-01-01T00:00:00Z",
            app=AppInfo(name="App", base_url="https://x.com", title="X"),
            browser=None,
            extension_version=None,
            duration_ms=1000,
            stats=CaptureStats(),
            capture_method="proxy",
        )
        json_str = manifest.model_dump_json()
        loaded = CaptureManifest.model_validate_json(json_str)
        assert loaded.browser is None
        assert loaded.capture_method == "proxy"
