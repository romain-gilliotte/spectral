"""Wrapper around ADB for interacting with Android devices."""

from __future__ import annotations

from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import zipfile

from cli.commands.android.external_tools.subprocess import run_cmd


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
    run_cmd(["adb", "devices"], "adb failed", timeout=10)


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

    result = run_cmd(cmd, "Failed to list packages", timeout=30)

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
    result = run_cmd(
        ["adb", "shell", "pm", "path", package],
        f"Package not found: {package}",
        timeout=15,
    )

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
    run_cmd(
        ["adb", "pull", remote_path, str(local_path)],
        "Failed to pull APK",
        timeout=120,
    )

    if not local_path.exists():
        raise AdbError(f"Pull succeeded but file not found at {local_path}")
    return local_path


def pull_apks(package: str, output: Path) -> tuple[Path, bool]:
    """Pull all APKs for a package from the device.

    Single APK → saved as a .apk file.
    Split APKs → packed into a .apks zip bundle.

    Args:
        package: Package name (e.g. "com.example.app").
        output: Destination path (.apk file or .apks bundle).

    Returns:
        Tuple of (output_path, is_split) where is_split is True if multiple APKs.
    """
    remote_paths = get_apk_paths(package)

    if len(remote_paths) == 1:
        pull_apk(remote_paths[0], output)
        return (output, False)

    # Multiple APKs → pull to temp dir then pack into .apks zip
    with tempfile.TemporaryDirectory(prefix="apk_pull_") as tmp:
        tmp_path = Path(tmp)
        pulled: list[Path] = []
        try:
            for remote_path in remote_paths:
                filename = remote_path.rsplit("/", 1)[-1]
                local_path = tmp_path / filename
                pull_apk(remote_path, local_path)
                pulled.append(local_path)
        except (AdbError, Exception):
            output.unlink(missing_ok=True)
            raise

        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w") as zf:
            for apk in pulled:
                zf.write(apk, apk.name)

    return (output, True)


def install_apk(path: Path) -> None:
    """Install an APK or .apks bundle to the device.

    Args:
        path: Path to a .apk file or a .apks zip bundle.
    """
    if path.suffix == ".apks":
        _install_apks_bundle(path)
    else:
        run_cmd(["adb", "install", "-r", str(path)], "Failed to install", timeout=120)


def _install_apks_bundle(bundle: Path) -> None:
    """Extract a .apks zip and install via adb install-multiple."""
    with tempfile.TemporaryDirectory(prefix="apk_install_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(bundle, "r") as zf:
            zf.extractall(tmp_path)
        apks = sorted(tmp_path.glob("*.apk"))
        if not apks:
            raise AdbError(f"No .apk files found in {bundle}")
        cmd = ["adb", "install-multiple", "-r"] + [str(a) for a in apks]
        run_cmd(cmd, "Failed to install", timeout=120)


def uninstall_app(package: str) -> None:
    """Uninstall a package from the connected device.

    Args:
        package: Package name (e.g. "com.example.app").
    """
    run_cmd(["adb", "uninstall", package], f"Failed to uninstall {package}", timeout=30)



def set_proxy(host: str, port: int) -> None:
    """Configure a global HTTP proxy on the connected Android device.

    Uses `adb shell settings put global http_proxy host:port`.
    This is ephemeral — it persists until cleared or device reboot.

    Args:
        host: The proxy host IP (your machine's LAN IP).
        port: The proxy port.
    """
    run_cmd(
        ["adb", "shell", "settings", "put", "global", "http_proxy", f"{host}:{port}"],
        "Failed to set proxy",
        timeout=10,
    )


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


def get_foreground_package() -> str | None:
    """Get the package name of the app currently in the foreground.

    Parses the ``mResumedActivity`` line from ``dumpsys activity activities``.
    Returns ``None`` when the foreground app cannot be determined (e.g. lock
    screen, no device connected).
    """
    import re

    try:
        result = run_cmd(
            ["adb", "shell", "dumpsys", "activity", "activities"],
            "Failed to query foreground activity",
            timeout=5,
        )
    except Exception:
        return None

    for line in result.stdout.splitlines():
        if "mResumedActivity" in line:
            # Format: mResumedActivity: ActivityRecord{hash u0 com.pkg/.Activity t123}
            m = re.search(r"(\S+)/\S+", line.split("mResumedActivity")[1])
            if m:
                return m.group(1)
    return None


def launch_app(package: str) -> None:
    """Launch the main activity of a package on the connected device.

    Uses `monkey` which doesn't require knowing the activity name.

    Args:
        package: Package name (e.g. "com.example.app").
    """
    run_cmd(
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
        f"Failed to launch {package}",
        timeout=15,
    )


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
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target, 80))
                ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            continue

    raise AdbError(
        "Could not detect LAN IP. Use --host to specify your machine's IP "
        "on the same network as the Android device."
    )
