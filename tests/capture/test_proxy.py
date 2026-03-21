"""Tests for the generic capture proxy engine (cli/capture/proxy.py)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cli.commands.capture._mitmproxy import (
    _domain_to_regex,
    flow_to_trace,
    ws_flow_to_connection,
)
from cli.commands.capture._wireguard import (
    build_wireguard_config,
    display_wireguard_config,
    get_local_ip,
)
from cli.commands.capture.discover import DiscoveryAddon
from cli.commands.capture.loader import load_bundle_bytes, write_bundle_bytes
from cli.commands.capture.proxy import CaptureAddon, FixedAppProvider
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
        addon = CaptureAddon(FixedAppProvider("test-app"))
        flow = _make_mock_flow()
        addon.response(flow)

        assert len(addon.traces) == 1
        assert addon.traces[0].meta.id == "t_0001"
        assert addon.traces[0].meta.app_package == "test-app"
        assert "api.example.com" in addon.domains_seen

    def test_multiple_responses_increment_counter(self) -> None:
        addon = CaptureAddon(FixedAppProvider("test-app"))
        for _ in range(3):
            addon.response(_make_mock_flow())

        assert len(addon.traces) == 3
        assert [t.meta.id for t in addon.traces] == ["t_0001", "t_0002", "t_0003"]

    def test_websocket_flow_skipped_in_response(self) -> None:
        addon = CaptureAddon(FixedAppProvider("test-app"))
        flow = _make_mock_flow()
        flow.websocket = MagicMock()  # Mark as WS flow
        addon.response(flow)

        assert len(addon.traces) == 0

    def test_options_flow_skipped(self) -> None:
        addon = CaptureAddon(FixedAppProvider("test-app"))
        flow = _make_mock_flow(method="OPTIONS")
        addon.response(flow)

        assert len(addon.traces) == 0

    def test_build_bundles_by_app(self) -> None:
        addon = CaptureAddon(FixedAppProvider("test-app"))
        addon.response(_make_mock_flow())
        addon.response(_make_mock_flow(url="https://api.example.com/users"))

        bundles = addon.build_bundles_by_app(1700000000.0, 1700000010.0)

        assert len(bundles) == 1
        bundle = bundles["test-app"]
        assert bundle.manifest.capture_method == "proxy"
        assert bundle.manifest.browser is None
        assert bundle.manifest.extension_version is None
        assert bundle.manifest.app.name == "test-app"
        assert bundle.manifest.stats.trace_count == 2
        assert bundle.manifest.stats.context_count == 0
        assert bundle.manifest.duration_ms == 10000
        assert len(bundle.traces) == 2
        assert len(bundle.contexts) == 0
        assert len(bundle.timeline.events) == 2

    def test_build_bundle_roundtrip(self) -> None:
        """Verify that the bundle produced by the addon can be written and loaded."""
        addon = CaptureAddon(FixedAppProvider("test-app"))
        addon.response(_make_mock_flow())

        bundles = addon.build_bundles_by_app(1700000000.0, 1700000005.0)
        bundle = bundles["test-app"]

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
    @patch("cli.commands.capture.discover.console")
    def test_tls_clienthello_logs_domain(self, mock_console: MagicMock) -> None:
        addon = DiscoveryAddon()
        data = MagicMock()
        data.context.client.sni = "api.example.com"
        data.ignore_connection = False

        addon.tls_clienthello(data)

        assert addon.domains == {"api.example.com": 1}
        assert data.ignore_connection is True
        mock_console.print.assert_called_once_with("  api.example.com")

    @patch("cli.commands.capture.discover.console")
    def test_multiple_domains_counted(self, mock_console: MagicMock) -> None:
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
        # print called only for new domains, not duplicates
        assert mock_console.print.call_count == 2

    @patch("cli.commands.capture.discover.console")
    def test_empty_sni_skipped(self, mock_console: MagicMock) -> None:
        addon = DiscoveryAddon()
        data = MagicMock()
        data.context.client.sni = ""

        addon.tls_clienthello(data)

        assert addon.domains == {}
        assert data.ignore_connection is True
        mock_console.print.assert_not_called()


class TestDomainToRegex:
    def test_glob_wildcard_prefix(self) -> None:
        assert _domain_to_regex("*.leboncoin.fr") == r".*\.leboncoin\.fr"

    def test_plain_domain_passes_through(self) -> None:
        # Plain domain is valid regex (dots match any char, which is fine)
        result = _domain_to_regex("api.leboncoin.fr")
        assert result == "api.leboncoin.fr"

    def test_valid_regex_passes_through(self) -> None:
        assert _domain_to_regex(r".*\.example\.com") == r".*\.example\.com"

    def test_bare_star_escaped(self) -> None:
        # "*" alone is invalid regex — should be escaped
        result = _domain_to_regex("*")
        assert result == r"\*"


class TestRunMitmproxyIgnoreHosts:
    @patch("mitmproxy.tools.dump.DumpMaster")
    @patch("mitmproxy.options.Options")
    def test_ignore_hosts_passed(
        self, mock_options_cls: MagicMock, mock_master_cls: MagicMock
    ) -> None:
        mock_opts = MagicMock()
        mock_options_cls.return_value = mock_opts

        async def _noop() -> None:
            pass

        mock_master = MagicMock()
        mock_master.run.return_value = _noop()
        mock_master_cls.return_value = mock_master

        # Make proxy_thread.is_alive() return False immediately
        with patch("cli.commands.capture._mitmproxy.threading.Thread") as mock_thread:
            mock_thread.return_value.is_alive.return_value = False
            from cli.commands.capture._mitmproxy import run_mitmproxy

            run_mitmproxy(
                8080,
                [],
                ignore_hosts=["*.google.com", "accounts.google.com"],
            )

        mock_opts.update.assert_any_call(
            ignore_hosts=[r".*\.google\.com", "accounts.google.com"]
        )


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


class TestGetLocalIp:
    def test_returns_ip(self) -> None:
        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("192.168.1.42", 12345)
        with patch("cli.commands.capture._wireguard.socket.socket", return_value=mock_sock):
            ip = get_local_ip()
        assert ip == "192.168.1.42"
        mock_sock.connect.assert_called_once_with(("8.8.8.8", 80))
        mock_sock.close.assert_called_once()

    def test_fallback_on_error(self) -> None:
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = OSError("no network")
        with patch("cli.commands.capture._wireguard.socket.socket", return_value=mock_sock):
            ip = get_local_ip()
        assert ip == "127.0.0.1"


class TestBuildWireguardConfig:
    @patch("cli.commands.capture._wireguard.get_local_ip", return_value="192.168.1.10")
    def test_generates_config_when_missing(self, _mock_ip: MagicMock, tmp_path: Path) -> None:
        fake_keys = iter(["server_priv_key", "client_priv_key"])
        fake_pubs: dict[str, str] = {"server_priv_key": "server_pub_key", "client_priv_key": "client_pub_key"}

        with (
            patch("cli.commands.capture._wireguard.storage.store_root", return_value=tmp_path),
            patch(
                "mitmproxy_rs.wireguard.genkey",
                side_effect=lambda: next(fake_keys),
            ),
            patch(
                "mitmproxy_rs.wireguard.pubkey",
                side_effect=lambda k: fake_pubs[k],  # pyright: ignore[reportUnknownLambdaType]
            ),
        ):
            config_text, mode_spec = build_wireguard_config(51820)

        assert "[Interface]" in config_text
        assert "[Peer]" in config_text
        assert "client_priv_key" in config_text
        assert "server_pub_key" in config_text
        assert "192.168.1.10:51820" in config_text

        conf_path: Path = tmp_path / "wireguard.conf"
        assert conf_path.exists()
        server_conf = json.loads(conf_path.read_text())
        # mitmproxy expects both values to be private keys
        assert server_conf["server_key"] == "server_priv_key"
        assert server_conf["client_key"] == "client_priv_key"

        assert mode_spec == f"wireguard:{conf_path}"

    @patch("cli.commands.capture._wireguard.get_local_ip", return_value="192.168.1.10")
    def test_reuses_existing_config(self, _mock_ip: MagicMock, tmp_path: Path) -> None:
        """When wireguard.conf already exists, keys are reused (no genkey calls)."""
        existing = {"server_key": "existing_srv", "client_key": "existing_cli"}
        (tmp_path / "wireguard.conf").write_text(json.dumps(existing))

        fake_pubs: dict[str, str] = {"existing_srv": "srv_pub", "existing_cli": "cli_pub"}
        mock_genkey = MagicMock()

        with (
            patch("cli.commands.capture._wireguard.storage.store_root", return_value=tmp_path),
            patch("mitmproxy_rs.wireguard.genkey", mock_genkey),
            patch(
                "mitmproxy_rs.wireguard.pubkey",
                side_effect=lambda k: fake_pubs[k],  # pyright: ignore[reportUnknownLambdaType]
            ),
        ):
            config_text, _ = build_wireguard_config(51820)

        mock_genkey.assert_not_called()
        assert "existing_cli" in config_text
        assert "srv_pub" in config_text


class TestDisplayWireguardConfig:
    @patch("cli.helpers.console.console")
    def test_display_without_segno(self, mock_console: MagicMock) -> None:
        import importlib
        import sys

        # Remove segno from sys.modules so the import fails
        saved = sys.modules.pop("segno", None)
        try:
            sys.modules["segno"] = None  # type: ignore[assignment]
            # Reload to pick up the mocked console
            import cli.commands.capture._wireguard as wg_mod

            importlib.reload(wg_mod)
            wg_mod.display_wireguard_config("[Interface]\nPrivateKey = abc\n")
        finally:
            if saved is not None:
                sys.modules["segno"] = saved
            else:
                sys.modules.pop("segno", None)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("[Interface]" in c for c in calls)
        assert any("segno" in c for c in calls)

    @patch("cli.helpers.console.console")
    def test_display_with_segno(self, mock_console: MagicMock) -> None:
        mock_qr = MagicMock()
        mock_segno = MagicMock()
        mock_segno.make.return_value = mock_qr

        import sys

        saved = sys.modules.get("segno")
        try:
            sys.modules["segno"] = mock_segno
            display_wireguard_config("[Interface]\nPrivateKey = abc\n")
        finally:
            if saved is not None:
                sys.modules["segno"] = saved
            else:
                sys.modules.pop("segno", None)

        mock_segno.make.assert_called_once()
        mock_qr.terminal.assert_called_once_with(compact=True)
