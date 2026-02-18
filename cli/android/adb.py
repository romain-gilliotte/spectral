"""Wrapper around ADB for interacting with Android devices."""

from __future__ import annotations

from pathlib import Path
import shutil
import socket
import subprocess


class AdbError(Exception):
    """Raised when an ADB operation fails."""


def check_adb() -> None:
    """Verify that adb is installed and accessible.

    Raises AdbError with installation instructions if not found.
    """
    if shutil.which("adb") is None:
        raise AdbError(
            "adb not found. Install Android SDK Platform Tools:\n"
            "  - macOS: brew install android-platform-tools\n"
            "  - Linux: sudo apt install android-tools-adb\n"
            "  - Or download from: https://developer.android.com/tools/releases/platform-tools"
        )
    # Verify adb can connect (will fail if no device)
    result = subprocess.run(
        ["adb", "devices"], capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        raise AdbError(f"adb failed: {result.stderr.strip()}")


def list_packages(filter_str: str | None = None) -> list[str]:
    """List installed packages on the connected device.

    Args:
        filter_str: Optional string to filter package names.

    Returns:
        List of package names (e.g. ["com.example.app", ...]).
    """
    cmd = ["adb", "shell", "pm", "list", "packages"]
    if filter_str:
        cmd.append(filter_str)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise AdbError(f"Failed to list packages: {result.stderr.strip()}")

    packages: list[str] = []
    for line in result.stdout.strip().splitlines():
        # Lines are "package:com.example.app"
        if line.startswith("package:"):
            packages.append(line[len("package:") :])
    return sorted(packages)


def get_apk_paths(package: str) -> list[str]:
    """Get the APK path(s) for a package on the device.

    Handles split APKs (returns all paths).

    Args:
        package: Package name (e.g. "com.example.app").

    Returns:
        List of remote APK paths on the device.
    """
    result = subprocess.run(
        ["adb", "shell", "pm", "path", package],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise AdbError(f"Package not found: {package}\n{result.stderr.strip()}")

    paths: list[str] = []
    for line in result.stdout.strip().splitlines():
        # Lines are "package:/data/app/.../base.apk"
        if line.startswith("package:"):
            paths.append(line[len("package:") :])
    if not paths:
        raise AdbError(f"No APK paths found for {package}")
    return paths


def pull_apk(remote_path: str, local_path: Path) -> Path:
    """Pull an APK from the device to a local path.

    Args:
        remote_path: Path on the Android device.
        local_path: Local destination path.

    Returns:
        The local path where the APK was saved.
    """
    result = subprocess.run(
        ["adb", "pull", remote_path, str(local_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise AdbError(f"Failed to pull APK: {result.stderr.strip()}")

    if not local_path.exists():
        raise AdbError(f"Pull succeeded but file not found at {local_path}")
    return local_path


def pull_apks(package: str, output: Path) -> tuple[Path, bool]:
    """Pull all APKs for a package from the device.

    Single APK → saves as a file (backward compat).
    Split APKs → creates a directory with all APKs, preserving device names.

    Args:
        package: Package name (e.g. "com.example.app").
        output: Destination path (used as file for single, directory for splits).

    Returns:
        Tuple of (output_path, is_split) where is_split is True if multiple APKs.
    """
    remote_paths = get_apk_paths(package)

    if len(remote_paths) == 1:
        # Single APK → pull as file
        pull_apk(remote_paths[0], output)
        return (output, False)

    # Multiple APKs → pull into directory
    output.mkdir(parents=True, exist_ok=True)
    pulled: list[Path] = []
    try:
        for remote_path in remote_paths:
            # Preserve the device filename (e.g. base.apk, split_config.arm64_v8a.apk)
            filename = remote_path.rsplit("/", 1)[-1]
            local_path = output / filename
            pull_apk(remote_path, local_path)
            pulled.append(local_path)
    except (AdbError, Exception):
        # Clean up on partial failure
        for p in pulled:
            p.unlink(missing_ok=True)
        if output.exists() and not any(output.iterdir()):
            output.rmdir()
        raise

    return (output, True)


def install_apk(path: Path) -> None:
    """Install an APK or directory of split APKs to the device.

    Args:
        path: Path to a single APK file or a directory containing split APKs.
    """
    if path.is_dir():
        apks = sorted(path.glob("*.apk"))
        if not apks:
            raise AdbError(f"No .apk files found in {path}")
        cmd = ["adb", "install-multiple", "-r"] + [str(a) for a in apks]
    else:
        cmd = ["adb", "install", "-r", str(path)]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise AdbError(f"Failed to install: {result.stderr.strip()}")


def set_proxy(host: str, port: int) -> None:
    """Configure a global HTTP proxy on the connected Android device.

    Uses `adb shell settings put global http_proxy host:port`.
    This is ephemeral — it persists until cleared or device reboot.

    Args:
        host: The proxy host IP (your machine's LAN IP).
        port: The proxy port.
    """
    result = subprocess.run(
        ["adb", "shell", "settings", "put", "global", "http_proxy", f"{host}:{port}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise AdbError(f"Failed to set proxy: {result.stderr.strip()}")


def clear_proxy() -> None:
    """Remove the global HTTP proxy setting from the connected Android device."""
    # Setting to :0 effectively clears it; on some devices we also need to delete
    subprocess.run(
        ["adb", "shell", "settings", "put", "global", "http_proxy", ":0"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    subprocess.run(
        ["adb", "shell", "settings", "delete", "global", "http_proxy"],
        capture_output=True,
        text=True,
        timeout=10,
    )


def launch_app(package: str) -> None:
    """Launch the main activity of a package on the connected device.

    Uses `monkey` which doesn't require knowing the activity name.

    Args:
        package: Package name (e.g. "com.example.app").
    """
    result = subprocess.run(
        [
            "adb",
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise AdbError(f"Failed to launch {package}: {result.stderr.strip()}")


def get_host_lan_ip() -> str:
    """Detect the LAN IP address of this machine that the device can reach.

    Opens a UDP socket toward the device's gateway to discover which local
    interface is routed. Falls back to connecting to a public DNS address
    if that fails.
    """
    # Try to find the IP via adb forward — the device gateway is usually
    # on the same subnet as our LAN IP.
    for target in ["8.8.8.8"]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target, 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            continue

    raise AdbError(
        "Could not detect LAN IP. Use --host to specify your machine's IP "
        "on the same network as the Android device."
    )
