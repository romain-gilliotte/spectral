"""Tests for the Android capture module (adb, patch, proxy)."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cli.android.adb import (
    AdbError,
    check_adb,
    clear_proxy,
    get_apk_paths,
    get_host_lan_ip,
    install_apk,
    launch_app,
    list_packages,
    pull_apk,
    pull_apks,
    set_proxy,
)
from cli.android.patch import (
    NETWORK_SECURITY_CONFIG,
    PatchError,
    _patch_manifest,
    patch_apk_dir,
    sign_apk,
)
from cli.android.proxy import CaptureAddon, flow_to_trace, ws_flow_to_connection
from cli.capture.loader import load_bundle_bytes, write_bundle_bytes
from cli.main import cli


# ── ADB tests ──────────────────────────────────────────────────────


class TestCheckAdb:
    def test_adb_not_found(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(AdbError, match="adb not found"):
                check_adb()

    def test_adb_found_success(self):
        with patch("shutil.which", return_value="/usr/bin/adb"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="List of devices\n", stderr=""
                )
                check_adb()  # Should not raise

    def test_adb_found_but_fails(self):
        with patch("shutil.which", return_value="/usr/bin/adb"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr="daemon not running"
                )
                with pytest.raises(AdbError, match="adb failed"):
                    check_adb()


class TestListPackages:
    def test_list_packages_basic(self):
        output = "package:com.example.app\npackage:com.example.other\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=output, stderr=""
            )
            pkgs = list_packages()
            assert pkgs == ["com.example.app", "com.example.other"]

    def test_list_packages_with_filter(self):
        output = "package:com.example.app\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=output, stderr=""
            )
            pkgs = list_packages("com.example")
            # Verify the filter was passed
            call_args = mock_run.call_args[0][0]
            assert "com.example" in call_args
            assert pkgs == ["com.example.app"]

    def test_list_packages_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error: no devices"
            )
            with pytest.raises(AdbError, match="Failed to list packages"):
                list_packages()


class TestGetApkPaths:
    def test_single_apk(self):
        output = "package:/data/app/com.example.app-1/base.apk\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=output, stderr=""
            )
            paths = get_apk_paths("com.example.app")
            assert paths == ["/data/app/com.example.app-1/base.apk"]

    def test_split_apks(self):
        output = (
            "package:/data/app/com.example.app-1/base.apk\n"
            "package:/data/app/com.example.app-1/split_config.arm64_v8a.apk\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=output, stderr=""
            )
            paths = get_apk_paths("com.example.app")
            assert len(paths) == 2

    def test_package_not_found(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=""
            )
            with pytest.raises(AdbError, match="Package not found"):
                get_apk_paths("com.nonexistent")


class TestPullApk:
    def test_pull_success(self, tmp_path):
        local_path = tmp_path / "app.apk"
        local_path.write_bytes(b"fake-apk")  # Simulate the pull result

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="1 file pulled\n", stderr=""
            )
            result = pull_apk("/data/app/base.apk", local_path)
            assert result == local_path

    def test_pull_failure(self, tmp_path):
        local_path = tmp_path / "app.apk"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="remote object does not exist"
            )
            with pytest.raises(AdbError, match="Failed to pull APK"):
                pull_apk("/data/app/base.apk", local_path)


class TestSetProxy:
    def test_set_proxy_success(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            set_proxy("192.168.1.10", 8080)
            cmd = mock_run.call_args[0][0]
            assert "settings" in cmd
            assert "192.168.1.10:8080" in cmd

    def test_set_proxy_failure(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="permission denied"
            )
            with pytest.raises(AdbError, match="Failed to set proxy"):
                set_proxy("192.168.1.10", 8080)


class TestClearProxy:
    def test_clear_proxy_runs_both_commands(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            clear_proxy()
            assert mock_run.call_count == 2
            # First call sets :0, second deletes
            first_cmd = mock_run.call_args_list[0][0][0]
            second_cmd = mock_run.call_args_list[1][0][0]
            assert ":0" in first_cmd
            assert "delete" in second_cmd


class TestLaunchApp:
    def test_launch_success(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Events injected: 1\n", stderr=""
            )
            launch_app("com.example.app")
            cmd = mock_run.call_args[0][0]
            assert "monkey" in cmd
            assert "com.example.app" in cmd

    def test_launch_failure(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="No activities found"
            )
            with pytest.raises(AdbError, match="Failed to launch"):
                launch_app("com.nonexistent")


class TestGetHostLanIp:
    def test_returns_lan_ip(self):
        import socket as socket_mod
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ("192.168.1.42", 12345)
        with patch.object(socket_mod, "socket", return_value=mock_socket):
            ip = get_host_lan_ip()
            assert ip == "192.168.1.42"

    def test_raises_on_failure(self):
        import socket as socket_mod
        mock_socket = MagicMock()
        mock_socket.connect.side_effect = OSError("Network unreachable")
        with patch.object(socket_mod, "socket", return_value=mock_socket):
            with pytest.raises(AdbError, match="Could not detect LAN IP"):
                get_host_lan_ip()


# ── Patch tests ────────────────────────────────────────────────────


class TestPatchManifest:
    def test_adds_network_security_config(self, tmp_path):
        manifest_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <manifest xmlns:android="http://schemas.android.com/apk/res/android"
                package="com.example.app">
                <application android:label="Test App">
                    <activity android:name=".MainActivity" />
                </application>
            </manifest>
        """)
        manifest_path = tmp_path / "AndroidManifest.xml"
        manifest_path.write_text(manifest_content)

        _patch_manifest(manifest_path)

        result = manifest_path.read_text()
        assert "networkSecurityConfig" in result
        assert "@xml/network_security_config" in result

    def test_existing_nsc_gets_overwritten(self, tmp_path):
        manifest_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <manifest xmlns:android="http://schemas.android.com/apk/res/android"
                package="com.example.app">
                <application
                    android:label="Test App"
                    android:networkSecurityConfig="@xml/old_config">
                </application>
            </manifest>
        """)
        manifest_path = tmp_path / "AndroidManifest.xml"
        manifest_path.write_text(manifest_content)

        _patch_manifest(manifest_path)

        result = manifest_path.read_text()
        assert "@xml/network_security_config" in result
        assert "@xml/old_config" not in result

    def test_no_application_element_raises(self, tmp_path):
        manifest_content = '<?xml version="1.0"?><manifest></manifest>'
        manifest_path = tmp_path / "AndroidManifest.xml"
        manifest_path.write_text(manifest_content)

        with pytest.raises(PatchError, match="No <application> element"):
            _patch_manifest(manifest_path)

    def test_network_security_config_content(self):
        """Verify the injected XML trusts both system and user CAs."""
        assert "system" in NETWORK_SECURITY_CONFIG
        assert "user" in NETWORK_SECURITY_CONFIG
        assert "trust-anchors" in NETWORK_SECURITY_CONFIG


# ── Proxy tests ────────────────────────────────────────────────────


def _make_mock_flow(
    method="GET",
    url="https://api.example.com/data",
    status=200,
    req_body=b"",
    resp_body=b'{"ok": true}',
    req_headers=None,
    resp_headers=None,
):
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
        return_value=list((resp_headers or {"Content-Type": "application/json"}).items())
    )

    flow.websocket = None
    return flow


class TestFlowToTrace:
    def test_basic_conversion(self):
        flow = _make_mock_flow()
        trace = flow_to_trace(flow, "t_0001")

        assert trace.meta.id == "t_0001"
        assert trace.meta.request.method == "GET"
        assert trace.meta.request.url == "https://api.example.com/data"
        assert trace.meta.response.status == 200
        assert trace.response_body == b'{"ok": true}'
        assert trace.meta.timing.total_ms == pytest.approx(150.0, abs=1.0)

    def test_post_with_body(self):
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

    def test_no_response_body(self):
        flow = _make_mock_flow(status=204, resp_body=b"")
        trace = flow_to_trace(flow, "t_0003")

        assert trace.meta.response.status == 204
        assert trace.response_body == b""
        assert trace.meta.response.body_file is None

    def test_headers_mapped(self):
        flow = _make_mock_flow(
            req_headers={"Authorization": "Bearer tok123", "Accept": "application/json"},
            resp_headers={"Content-Type": "application/json", "X-Request-Id": "abc"},
        )
        trace = flow_to_trace(flow, "t_0004")

        assert len(trace.meta.request.headers) == 2
        assert len(trace.meta.response.headers) == 2

    def test_initiator_is_proxy(self):
        flow = _make_mock_flow()
        trace = flow_to_trace(flow, "t_0005")
        assert trace.meta.initiator.type == "proxy"


class TestCaptureAddon:
    def test_response_adds_trace(self):
        addon = CaptureAddon()
        flow = _make_mock_flow()
        addon.response(flow)

        assert len(addon.traces) == 1
        assert addon.traces[0].meta.id == "t_0001"
        assert "api.example.com" in addon.domains_seen

    def test_multiple_responses_increment_counter(self):
        addon = CaptureAddon()
        for _ in range(3):
            addon.response(_make_mock_flow())

        assert len(addon.traces) == 3
        assert [t.meta.id for t in addon.traces] == ["t_0001", "t_0002", "t_0003"]

    def test_websocket_flow_skipped_in_response(self):
        addon = CaptureAddon()
        flow = _make_mock_flow()
        flow.websocket = MagicMock()  # Mark as WS flow
        addon.response(flow)

        assert len(addon.traces) == 0

    def test_build_bundle(self):
        addon = CaptureAddon()
        addon.response(_make_mock_flow())
        addon.response(_make_mock_flow(url="https://api.example.com/users"))

        bundle = addon.build_bundle("Test App", 1700000000.0, 1700000010.0)

        assert bundle.manifest.capture_method == "android_proxy"
        assert bundle.manifest.browser is None
        assert bundle.manifest.extension_version is None
        assert bundle.manifest.app.name == "Test App"
        assert bundle.manifest.stats.trace_count == 2
        assert bundle.manifest.stats.context_count == 0
        assert bundle.manifest.duration_ms == 10000
        assert len(bundle.traces) == 2
        assert len(bundle.contexts) == 0
        assert len(bundle.timeline.events) == 2

    def test_build_bundle_roundtrip(self):
        """Verify that the bundle produced by the addon can be written and loaded."""
        addon = CaptureAddon()
        addon.response(_make_mock_flow())

        bundle = addon.build_bundle("Test App", 1700000000.0, 1700000005.0)

        data = write_bundle_bytes(bundle)
        loaded = load_bundle_bytes(data)

        assert loaded.manifest.capture_method == "android_proxy"
        assert loaded.manifest.browser is None
        assert len(loaded.traces) == 1
        assert loaded.traces[0].meta.request.method == "GET"
        assert loaded.traces[0].response_body == b'{"ok": true}'


class TestWsFlowToConnection:
    def test_basic_ws_connection(self):
        flow = MagicMock()
        flow.request.pretty_url = "wss://ws.example.com/socket"
        flow.request.timestamp_start = 1700000000.0
        flow.request.headers.get = MagicMock(return_value="graphql-ws")

        conn = ws_flow_to_connection(flow, "ws_0001", [])

        assert conn.meta.id == "ws_0001"
        assert conn.meta.url == "wss://ws.example.com/socket"
        assert conn.meta.protocols == ["graphql-ws"]
        assert conn.meta.message_count == 0

    def test_ws_with_messages(self):
        from cli.capture.models import WsMessage
        from cli.formats.capture_bundle import WsMessageMeta

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


# ── pull_apks tests ────────────────────────────────────────────────


class TestPullApks:
    def test_single_apk_pulls_as_file(self, tmp_path):
        output = tmp_path / "app.apk"

        def fake_run(cmd, **kwargs):
            # get_apk_paths call
            if "pm" in cmd and "path" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout="package:/data/app/com.example-1/base.apk\n", stderr=""
                )
            # pull call
            if "pull" in cmd:
                # Simulate adb pull creating the file
                Path(cmd[-1]).write_bytes(b"fake-apk-data")
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="1 file pulled\n", stderr=""
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result_path, is_split = pull_apks("com.example", output)

        assert is_split is False
        assert result_path == output
        assert result_path.is_file()

    def test_split_apks_pulls_as_directory(self, tmp_path):
        output = tmp_path / "com.example"

        remote_paths = [
            "package:/data/app/com.example-1/base.apk",
            "package:/data/app/com.example-1/split_config.arm64_v8a.apk",
            "package:/data/app/com.example-1/split_config.fr.apk",
        ]

        def fake_run(cmd, **kwargs):
            if "pm" in cmd and "path" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout="\n".join(remote_paths) + "\n", stderr=""
                )
            if "pull" in cmd:
                Path(cmd[-1]).write_bytes(b"fake-apk-data")
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="1 file pulled\n", stderr=""
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result_path, is_split = pull_apks("com.example", output)

        assert is_split is True
        assert result_path == output
        assert result_path.is_dir()
        assert (result_path / "base.apk").exists()
        assert (result_path / "split_config.arm64_v8a.apk").exists()
        assert (result_path / "split_config.fr.apk").exists()

    def test_split_apks_preserves_device_filenames(self, tmp_path):
        output = tmp_path / "com.example"

        def fake_run(cmd, **kwargs):
            if "pm" in cmd and "path" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout=(
                        "package:/data/app/com.example-1/base.apk\n"
                        "package:/data/app/com.example-1/split_config.xxhdpi.apk\n"
                    ),
                    stderr=""
                )
            if "pull" in cmd:
                Path(cmd[-1]).write_bytes(b"data")
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="", stderr=""
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result_path, _ = pull_apks("com.example", output)

        filenames = {f.name for f in result_path.glob("*.apk")}
        assert filenames == {"base.apk", "split_config.xxhdpi.apk"}

    def test_partial_failure_cleans_up(self, tmp_path):
        output = tmp_path / "com.example"
        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            if "pm" in cmd and "path" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout=(
                        "package:/data/app/com.example-1/base.apk\n"
                        "package:/data/app/com.example-1/split_config.arm64_v8a.apk\n"
                    ),
                    stderr=""
                )
            if "pull" in cmd:
                call_count += 1
                if call_count == 1:
                    # First pull succeeds
                    Path(cmd[-1]).write_bytes(b"data")
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=0, stdout="", stderr=""
                    )
                else:
                    # Second pull fails
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=1, stdout="", stderr="device offline"
                    )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(AdbError, match="Failed to pull APK"):
                pull_apks("com.example", output)

        # Cleaned up: pulled files should be removed
        if output.exists():
            assert not any(output.iterdir())


# ── install_apk tests ─────────────────────────────────────────────


class TestInstallApk:
    def test_single_file_uses_adb_install(self, tmp_path):
        apk = tmp_path / "app.apk"
        apk.write_bytes(b"fake")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Success\n", stderr=""
            )
            install_apk(apk)

            cmd = mock_run.call_args[0][0]
            assert cmd[:3] == ["adb", "install", "-r"]
            assert str(apk) in cmd

    def test_directory_uses_adb_install_multiple(self, tmp_path):
        apk_dir = tmp_path / "splits"
        apk_dir.mkdir()
        (apk_dir / "base.apk").write_bytes(b"base")
        (apk_dir / "split_config.arm64_v8a.apk").write_bytes(b"split1")
        (apk_dir / "split_config.fr.apk").write_bytes(b"split2")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Success\n", stderr=""
            )
            install_apk(apk_dir)

            cmd = mock_run.call_args[0][0]
            assert cmd[:3] == ["adb", "install-multiple", "-r"]
            apk_args = cmd[3:]
            assert len(apk_args) == 3

    def test_empty_directory_raises(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with pytest.raises(AdbError, match="No .apk files found"):
            install_apk(empty_dir)

    def test_install_failure_raises(self, tmp_path):
        apk = tmp_path / "app.apk"
        apk.write_bytes(b"fake")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="INSTALL_FAILED_ALREADY_EXISTS"
            )
            with pytest.raises(AdbError, match="Failed to install"):
                install_apk(apk)


# ── sign_apk tests ────────────────────────────────────────────────


class TestSignApk:
    def test_sign_apk_calls_signing_tool(self, tmp_path):
        input_apk = tmp_path / "input.apk"
        input_apk.write_bytes(b"fake-apk")
        output_apk = tmp_path / "output.apk"
        keystore = tmp_path / "debug.keystore"
        keystore.write_bytes(b"fake-keystore")

        with patch("cli.android.patch._ensure_tools"):
            with patch("cli.android.patch._sign_apk") as mock_sign:
                result = sign_apk(input_apk, output_apk, keystore)
                mock_sign.assert_called_once_with(input_apk, output_apk, keystore)
                assert result == output_apk


# ── patch_apk_dir tests ──────────────────────────────────────────


class TestPatchApkDir:
    def test_patches_base_and_resigns_splits(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "base.apk").write_bytes(b"base-data")
        (input_dir / "split_config.arm64_v8a.apk").write_bytes(b"split1")
        (input_dir / "split_config.fr.apk").write_bytes(b"split2")
        output_dir = tmp_path / "output"

        with patch("cli.android.patch._ensure_tools"):
            with patch("cli.android.patch._ensure_debug_keystore"):
                with patch("cli.android.patch.patch_apk") as mock_patch:
                    with patch("cli.android.patch.sign_apk") as mock_sign:
                        # patch_apk creates the output file
                        def fake_patch(apk, out, keystore):
                            out.parent.mkdir(parents=True, exist_ok=True)
                            out.write_bytes(b"patched")
                            return out

                        def fake_sign(apk, out, ks):
                            out.write_bytes(b"signed")
                            return out

                        mock_patch.side_effect = fake_patch
                        mock_sign.side_effect = fake_sign

                        result = patch_apk_dir(input_dir, output_dir)

        assert result == output_dir
        assert result.is_dir()
        # patch_apk called for base
        assert mock_patch.call_count == 1
        base_call = mock_patch.call_args
        assert base_call[0][0] == input_dir / "base.apk"
        assert base_call[0][1] == output_dir / "base.apk"
        assert base_call[1]["keystore"] is not None
        # sign_apk called for splits
        assert mock_sign.call_count == 2
        signed_names = {call[0][0].name for call in mock_sign.call_args_list}
        assert signed_names == {"split_config.arm64_v8a.apk", "split_config.fr.apk"}

    def test_uses_first_apk_when_no_base(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        # No base.apk, only splits
        (input_dir / "app.apk").write_bytes(b"app-data")
        (input_dir / "split.apk").write_bytes(b"split-data")
        output_dir = tmp_path / "output"

        with patch("cli.android.patch._ensure_tools"):
            with patch("cli.android.patch._ensure_debug_keystore"):
                with patch("cli.android.patch.patch_apk") as mock_patch:
                    with patch("cli.android.patch.sign_apk") as mock_sign:
                        mock_patch.side_effect = lambda apk, out, keystore: (
                            out.parent.mkdir(parents=True, exist_ok=True) or
                            out.write_bytes(b"patched") or out
                        )
                        mock_sign.side_effect = lambda apk, out, ks: (
                            out.write_bytes(b"signed") or out
                        )

                        patch_apk_dir(input_dir, output_dir)

        # First sorted APK (app.apk) used as base
        patched_apk = mock_patch.call_args[0][0]
        assert patched_apk.name == "app.apk"
        # split.apk re-signed
        assert mock_sign.call_count == 1
        assert mock_sign.call_args[0][0].name == "split.apk"

    def test_empty_dir_raises(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        with pytest.raises(PatchError, match="No .apk files found"):
            patch_apk_dir(input_dir, output_dir)

    def test_all_apks_share_keystore(self, tmp_path):
        """All APKs should be signed with the same keystore."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "base.apk").write_bytes(b"base")
        (input_dir / "split.apk").write_bytes(b"split")
        output_dir = tmp_path / "output"

        keystores_used = []

        with patch("cli.android.patch._ensure_tools"):
            with patch("cli.android.patch._ensure_debug_keystore"):
                with patch("cli.android.patch.patch_apk") as mock_patch:
                    with patch("cli.android.patch.sign_apk") as mock_sign:
                        def capture_patch(apk, out, keystore):
                            keystores_used.append(keystore)
                            out.parent.mkdir(parents=True, exist_ok=True)
                            out.write_bytes(b"patched")
                            return out

                        def capture_sign(apk, out, ks):
                            keystores_used.append(ks)
                            out.write_bytes(b"signed")
                            return out

                        mock_patch.side_effect = capture_patch
                        mock_sign.side_effect = capture_sign

                        patch_apk_dir(input_dir, output_dir)

        # Both calls should use the same keystore
        assert len(keystores_used) == 2
        assert keystores_used[0] == keystores_used[1]


# ── CLI integration tests ─────────────────────────────────────────


class TestAndroidCLI:
    def test_android_group_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["android", "--help"])
        assert result.exit_code == 0
        assert "pull" in result.output
        assert "patch" in result.output
        assert "install" in result.output
        assert "capture" in result.output

    def test_pull_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["android", "pull", "--help"])
        assert result.exit_code == 0
        assert "PACKAGE" in result.output

    def test_patch_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["android", "patch", "--help"])
        assert result.exit_code == 0
        assert "APK_PATH" in result.output

    def test_install_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["android", "install", "--help"])
        assert result.exit_code == 0
        assert "APK_PATH" in result.output

    def test_capture_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["android", "capture", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--output" in result.output
        assert "--domain" in result.output


# ── Manifest backward compatibility ───────────────────────────────


class TestManifestCompat:
    def test_existing_manifests_still_parse(self):
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

    def test_android_manifest_no_browser(self):
        from cli.formats.capture_bundle import (
            AppInfo,
            CaptureManifest,
            CaptureStats,
        )

        manifest = CaptureManifest(
            capture_id="test",
            created_at="2026-01-01T00:00:00Z",
            app=AppInfo(name="Android App", base_url="https://api.app.com", title="App"),
            browser=None,
            extension_version=None,
            duration_ms=5000,
            stats=CaptureStats(trace_count=10),
            capture_method="android_proxy",
        )
        assert manifest.browser is None
        assert manifest.extension_version is None
        assert manifest.capture_method == "android_proxy"

    def test_manifest_json_roundtrip_without_browser(self):
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
            capture_method="android_proxy",
        )
        json_str = manifest.model_dump_json()
        loaded = CaptureManifest.model_validate_json(json_str)
        assert loaded.browser is None
        assert loaded.capture_method == "android_proxy"
