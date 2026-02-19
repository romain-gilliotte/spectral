"""Tests for ADB wrapper functions."""

from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from cli.commands.android.adb import (
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
    push_cert,
    set_proxy,
)


class TestCheckAdb:
    def test_adb_not_found(self) -> None:
        with patch("shutil.which", return_value=None):
            with pytest.raises(AdbError, match="adb not found"):
                check_adb()

    def test_adb_found_success(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/adb"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="List of devices\n", stderr=""
                )
                check_adb()  # Should not raise

    def test_adb_found_but_fails(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/adb"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr="daemon not running"
                )
                with pytest.raises(RuntimeError, match="adb failed"):
                    check_adb()


class TestListPackages:
    def test_list_packages_basic(self) -> None:
        output = "package:com.example.app\npackage:com.example.other\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=output, stderr=""
            )
            pkgs = list_packages()
            assert pkgs == ["com.example.app", "com.example.other"]

    def test_list_packages_with_filter(self) -> None:
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

    def test_list_packages_error(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error: no devices"
            )
            with pytest.raises(RuntimeError, match="Failed to list packages"):
                list_packages()


class TestGetApkPaths:
    def test_single_apk(self) -> None:
        output = "package:/data/app/com.example.app-1/base.apk\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=output, stderr=""
            )
            paths = get_apk_paths("com.example.app")
            assert paths == ["/data/app/com.example.app-1/base.apk"]

    def test_split_apks(self) -> None:
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

    def test_package_not_found(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=""
            )
            with pytest.raises(RuntimeError, match="Package not found"):
                get_apk_paths("com.nonexistent")


class TestPullApk:
    def test_pull_success(self, tmp_path: Path) -> None:
        local_path = tmp_path / "app.apk"
        local_path.write_bytes(b"fake-apk")  # Simulate the pull result

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="1 file pulled\n", stderr=""
            )
            result = pull_apk("/data/app/base.apk", local_path)
            assert result == local_path

    def test_pull_failure(self, tmp_path: Path) -> None:
        local_path = tmp_path / "app.apk"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="remote object does not exist"
            )
            with pytest.raises(RuntimeError, match="Failed to pull APK"):
                pull_apk("/data/app/base.apk", local_path)


class TestPushCert:
    def test_push_success(self, tmp_path: Path) -> None:
        cert = tmp_path / "mitmproxy-ca-cert.pem"
        cert.write_text("fake cert")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="1 file pushed\n", stderr=""
            )
            device_filename = push_cert(cert)

        assert device_filename == "mitmproxy-ca-cert.crt"
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "adb"
        assert cmd[1] == "push"
        assert "/sdcard/mitmproxy-ca-cert.crt" in cmd

    def test_push_failure(self, tmp_path: Path) -> None:
        cert = tmp_path / "my-cert.pem"
        cert.write_text("fake cert")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="device offline"
            )
            with pytest.raises(RuntimeError, match="Failed to push cert"):
                push_cert(cert)

    def test_custom_cert_name(self, tmp_path: Path) -> None:
        cert = tmp_path / "custom-ca.pem"
        cert.write_text("fake cert")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            device_filename = push_cert(cert)

        assert device_filename == "custom-ca.crt"


class TestSetProxy:
    def test_set_proxy_success(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            set_proxy("192.168.1.10", 8080)
            cmd = mock_run.call_args[0][0]
            assert "settings" in cmd
            assert "192.168.1.10:8080" in cmd

    def test_set_proxy_failure(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="permission denied"
            )
            with pytest.raises(RuntimeError, match="Failed to set proxy"):
                set_proxy("192.168.1.10", 8080)


class TestClearProxy:
    def test_clear_proxy_runs_both_commands(self) -> None:
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
    def test_launch_success(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Events injected: 1\n", stderr=""
            )
            launch_app("com.example.app")
            cmd = mock_run.call_args[0][0]
            assert "monkey" in cmd
            assert "com.example.app" in cmd

    def test_launch_failure(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="No activities found"
            )
            with pytest.raises(RuntimeError, match="Failed to launch"):
                launch_app("com.nonexistent")


class TestGetHostLanIp:
    def test_returns_lan_ip(self) -> None:
        import socket as socket_mod

        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ("192.168.1.42", 12345)
        with patch.object(socket_mod, "socket", return_value=mock_socket):
            ip = get_host_lan_ip()
            assert ip == "192.168.1.42"

    def test_raises_on_failure(self) -> None:
        import socket as socket_mod

        mock_socket = MagicMock()
        mock_socket.connect.side_effect = OSError("Network unreachable")
        with patch.object(socket_mod, "socket", return_value=mock_socket):
            with pytest.raises(AdbError, match="Could not detect LAN IP"):
                get_host_lan_ip()


class TestPullApks:
    def test_single_apk_pulls_as_file(self, tmp_path: Path) -> None:
        output = tmp_path / "app.apk"

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            # get_apk_paths call
            if "pm" in cmd and "path" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="package:/data/app/com.example-1/base.apk\n",
                    stderr="",
                )
            # pull call
            if "pull" in cmd:
                # Simulate adb pull creating the file
                Path(cmd[-1]).write_bytes(b"fake-apk-data")
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="1 file pulled\n", stderr=""
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        with patch("subprocess.run", side_effect=fake_run):
            result_path, is_split = pull_apks("com.example", output)

        assert is_split is False
        assert result_path == output
        assert result_path.is_file()

    def test_split_apks_pulls_as_directory(self, tmp_path: Path) -> None:
        output = tmp_path / "com.example"

        remote_paths = [
            "package:/data/app/com.example-1/base.apk",
            "package:/data/app/com.example-1/split_config.arm64_v8a.apk",
            "package:/data/app/com.example-1/split_config.fr.apk",
        ]

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if "pm" in cmd and "path" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="\n".join(remote_paths) + "\n",
                    stderr="",
                )
            if "pull" in cmd:
                Path(cmd[-1]).write_bytes(b"fake-apk-data")
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="1 file pulled\n", stderr=""
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        with patch("subprocess.run", side_effect=fake_run):
            result_path, is_split = pull_apks("com.example", output)

        assert is_split is True
        assert result_path == output
        assert result_path.is_dir()
        assert (result_path / "base.apk").exists()
        assert (result_path / "split_config.arm64_v8a.apk").exists()
        assert (result_path / "split_config.fr.apk").exists()

    def test_split_apks_preserves_device_filenames(self, tmp_path: Path) -> None:
        output = tmp_path / "com.example"

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if "pm" in cmd and "path" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout=(
                        "package:/data/app/com.example-1/base.apk\n"
                        "package:/data/app/com.example-1/split_config.xxhdpi.apk\n"
                    ),
                    stderr="",
                )
            if "pull" in cmd:
                Path(cmd[-1]).write_bytes(b"data")
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="", stderr=""
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        with patch("subprocess.run", side_effect=fake_run):
            result_path, _ = pull_apks("com.example", output)

        filenames = {f.name for f in result_path.glob("*.apk")}
        assert filenames == {"base.apk", "split_config.xxhdpi.apk"}

    def test_partial_failure_cleans_up(self, tmp_path: Path) -> None:
        output = tmp_path / "com.example"
        call_count = 0

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            if "pm" in cmd and "path" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout=(
                        "package:/data/app/com.example-1/base.apk\n"
                        "package:/data/app/com.example-1/split_config.arm64_v8a.apk\n"
                    ),
                    stderr="",
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
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="Failed to pull APK"):
                pull_apks("com.example", output)

        # Cleaned up: pulled files should be removed
        if output.exists():
            assert not any(output.iterdir())


class TestInstallApk:
    def test_single_file_uses_adb_install(self, tmp_path: Path) -> None:
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

    def test_directory_uses_adb_install_multiple(self, tmp_path: Path) -> None:
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

    def test_empty_directory_raises(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with pytest.raises(AdbError, match="No .apk files found"):
            install_apk(empty_dir)

    def test_install_failure_raises(self, tmp_path: Path) -> None:
        apk = tmp_path / "app.apk"
        apk.write_bytes(b"fake")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="INSTALL_FAILED_ALREADY_EXISTS"
            )
            with pytest.raises(RuntimeError, match="Failed to install"):
                install_apk(apk)
