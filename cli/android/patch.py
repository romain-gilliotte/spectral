"""APK patching to trust user CA certificates for MITM interception."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

NETWORK_SECURITY_CONFIG = """\
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <base-config>
    <trust-anchors>
      <certificates src="system" />
      <certificates src="user" />
    </trust-anchors>
  </base-config>
</network-security-config>
"""

ANDROID_NS = "http://schemas.android.com/apk/res/android"

# tools/ directory at project root, auto-downloaded jars live here
_TOOLS_DIR = Path(__file__).resolve().parent.parent.parent / "tools"

# Pinned versions — downloaded on first use
_APKTOOL_VERSION = "2.11.1"
_APKTOOL_URL = f"https://github.com/iBotPeaches/Apktool/releases/download/v{_APKTOOL_VERSION}/apktool_{_APKTOOL_VERSION}.jar"
_APKTOOL_JAR = _TOOLS_DIR / "apktool.jar"

_UBER_SIGNER_VERSION = "1.3.0"
_UBER_SIGNER_URL = f"https://github.com/patrickfav/uber-apk-signer/releases/download/v{_UBER_SIGNER_VERSION}/uber-apk-signer-{_UBER_SIGNER_VERSION}.jar"
_UBER_SIGNER_JAR = _TOOLS_DIR / "uber-apk-signer.jar"


class PatchError(Exception):
    """Raised when APK patching fails."""


# ── Tool bootstrap ───────────────────────────────────────────────


def _download_jar(url: str, dest: Path, name: str) -> None:
    """Download a JAR file if it doesn't already exist."""
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise PatchError(f"Failed to download {name}: {e}")


def _ensure_tools() -> None:
    """Download apktool + uber-apk-signer on first use. Requires Java."""
    if shutil.which("java") is None:
        raise PatchError("java not found. Install Java JDK 11+.")
    _download_jar(_APKTOOL_URL, _APKTOOL_JAR, "apktool")
    _download_jar(_UBER_SIGNER_URL, _UBER_SIGNER_JAR, "uber-apk-signer")


def _apktool() -> list[str]:
    return ["java", "-jar", str(_APKTOOL_JAR)]


def _uber_signer() -> list[str]:
    return ["java", "-jar", str(_UBER_SIGNER_JAR)]


# ── Public API ────────────────────────────────────────────────────


def patch_apk(apk_path: Path, output_path: Path, keystore: Path | None = None) -> Path:
    """Patch an APK to trust user CA certificates.

    Uses apktool with --no-src (skip DEX disassembly for speed).
    Injects or replaces network_security_config.xml to trust user CAs,
    fixes known resource issues, then rebuilds and signs.

    Args:
        apk_path: Path to the original APK.
        output_path: Path for the patched APK.
        keystore: Optional path to a keystore for signing. If None, creates a
            temporary debug keystore.

    Returns:
        Path to the signed, patched APK.
    """
    _ensure_tools()

    with tempfile.TemporaryDirectory(prefix="apk_patch_") as tmpdir:
        work_dir = Path(tmpdir) / "decompiled"
        unsigned_apk = Path(tmpdir) / "unsigned.apk"

        # 1. Decompile (--no-src skips DEX disassembly — much faster)
        _run_cmd(
            [*_apktool(), "d", "--no-src", str(apk_path), "-o", str(work_dir), "-f"],
            "Decompiling APK",
        )

        # 2. Inject/replace network_security_config.xml
        _inject_nsc(work_dir)

        # 3. Ensure manifest references it
        _patch_manifest(work_dir / "AndroidManifest.xml")

        # 4. Fix known resource compatibility issues
        _fix_resources(work_dir)

        # 5. Recompile
        _run_cmd(
            [*_apktool(), "b", str(work_dir), "-o", str(unsigned_apk)],
            "Recompiling APK",
        )

        # 6. Sign
        if keystore is None:
            keystore = Path(tmpdir) / "debug.keystore"
        _ensure_debug_keystore(keystore)
        _sign_apk(unsigned_apk, output_path, keystore)

    return output_path


def sign_apk(apk_path: Path, output_path: Path, keystore: Path) -> Path:
    """Re-sign an APK with the given keystore (no patching).

    Used for split APKs that need the same signature as the patched base.

    Args:
        apk_path: Path to the APK to sign.
        output_path: Path for the signed APK.
        keystore: Path to the keystore to use.

    Returns:
        Path to the signed APK.
    """
    _ensure_tools()
    _sign_apk(apk_path, output_path, keystore)
    return output_path


def patch_apk_dir(input_dir: Path, output_dir: Path) -> Path:
    """Patch a directory of split APKs for MITM interception.

    Patches base.apk (decompile + network security config + recompile + sign)
    and re-signs all other split APKs with the same debug keystore so they
    can be installed together via adb install-multiple.

    Args:
        input_dir: Directory containing base.apk and split_*.apk files.
        output_dir: Directory for the patched output.

    Returns:
        Path to the output directory.
    """
    apks = sorted(input_dir.glob("*.apk"))
    if not apks:
        raise PatchError(f"No .apk files found in {input_dir}")

    # Identify the base APK
    base_apk = None
    for apk in apks:
        if apk.name == "base.apk":
            base_apk = apk
            break
    if base_apk is None:
        base_apk = apks[0]

    output_dir.mkdir(parents=True, exist_ok=True)

    # Create a shared debug keystore
    with tempfile.TemporaryDirectory(prefix="apk_ks_") as ks_dir:
        keystore = Path(ks_dir) / "debug.keystore"
        _ensure_debug_keystore(keystore)

        # Patch the base APK (decompile + inject + recompile + sign)
        patch_apk(base_apk, output_dir / base_apk.name, keystore=keystore)

        # Re-sign the split APKs with the same keystore
        for apk in apks:
            if apk == base_apk:
                continue
            sign_apk(apk, output_dir / apk.name, keystore)

    return output_dir


# ── Internals ─────────────────────────────────────────────────────


def _inject_nsc(work_dir: Path) -> None:
    """Inject or replace network_security_config.xml to trust user CAs."""
    xml_dir = work_dir / "res" / "xml"
    xml_dir.mkdir(parents=True, exist_ok=True)
    nsc_path = xml_dir / "network_security_config.xml"
    nsc_path.write_text(NETWORK_SECURITY_CONFIG)


def _patch_manifest(manifest_path: Path) -> None:
    """Add networkSecurityConfig attribute to the <application> element."""
    ET.register_namespace("android", ANDROID_NS)

    tree = ET.parse(manifest_path)
    root = tree.getroot()

    app_elem = root.find("application")
    if app_elem is None:
        raise PatchError("No <application> element found in AndroidManifest.xml")

    ns_attr = f"{{{ANDROID_NS}}}networkSecurityConfig"
    app_elem.set(ns_attr, "@xml/network_security_config")

    tree.write(manifest_path, encoding="utf-8", xml_declaration=True)


def _fix_resources(work_dir: Path) -> None:
    """Fix known resource compatibility issues that break apktool rebuild.

    - _generated_res_locale_config.xml: uses android:defaultLocale (API 34+)
      which older aapt2 versions don't know. Strip the unsupported attribute.
    """
    locale_config = work_dir / "res" / "xml" / "_generated_res_locale_config.xml"
    if locale_config.exists():
        content = locale_config.read_text()
        if "android:defaultLocale" in content:
            fixed = re.sub(r'\s+android:defaultLocale="[^"]*"', "", content)
            locale_config.write_text(fixed)


def _ensure_debug_keystore(keystore_path: Path) -> None:
    """Create a debug keystore if it doesn't exist."""
    if keystore_path.exists():
        return

    _run_cmd(
        [
            "keytool", "-genkey",
            "-v",
            "-keystore", str(keystore_path),
            "-alias", "debug",
            "-keyalg", "RSA",
            "-keysize", "2048",
            "-validity", "10000",
            "-storepass", "android",
            "-keypass", "android",
            "-dname", "CN=Debug,O=Debug,C=US",
        ],
        "Generating debug keystore",
    )


def _sign_apk(unsigned_apk: Path, output_path: Path, keystore: Path) -> None:
    """Sign an APK with v1+v2+v3 schemes using uber-apk-signer."""
    with tempfile.TemporaryDirectory(prefix="apk_sign_") as sign_dir:
        staging = Path(sign_dir) / "input" / unsigned_apk.name
        staging.parent.mkdir()
        shutil.copy2(unsigned_apk, staging)

        _run_cmd(
            [
                *_uber_signer(),
                "--apks", str(staging.parent),
                "--ks", str(keystore),
                "--ksPass", "android",
                "--ksAlias", "debug",
                "--ksKeyPass", "android",
                "--out", str(Path(sign_dir) / "out"),
                "--allowResign",
            ],
            "Signing APK",
        )

        signed_files = list((Path(sign_dir) / "out").glob("*-aligned-signed.apk"))
        if not signed_files:
            raise PatchError("uber-apk-signer produced no output")
        shutil.copy2(signed_files[0], output_path)


def _run_cmd(cmd: list[str], description: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command, raising PatchError on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise PatchError(
            f"{description} failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return result
