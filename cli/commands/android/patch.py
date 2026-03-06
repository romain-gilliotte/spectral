"""APK patching to trust user CA certificates for MITM interception."""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
from xml.etree import ElementTree as ET

from cli.commands.android.external_tools import apktool, uber_signer

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


class PatchError(Exception):
    """Raised when APK patching fails."""


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
    apktool.ensure()
    uber_signer.ensure()

    with tempfile.TemporaryDirectory(prefix="apk_patch_") as tmpdir:
        work_dir = Path(tmpdir) / "decompiled"
        unsigned_apk = Path(tmpdir) / "unsigned.apk"

        # 1. Decompile (--no-src skips DEX disassembly — much faster)
        apktool.decompile(apk_path, work_dir)

        # 2. Inject/replace network_security_config.xml
        _inject_nsc(work_dir)

        # 3. Ensure manifest references it
        _patch_manifest(work_dir / "AndroidManifest.xml")

        # 4. Fix known resource compatibility issues
        _fix_resources(work_dir)

        # 5. Recompile
        apktool.build(work_dir, unsigned_apk)

        # 6. Sign
        if keystore is None:
            keystore = Path(tmpdir) / "debug.keystore"
        uber_signer.ensure_debug_keystore(keystore)
        uber_signer.sign(unsigned_apk, output_path, keystore)

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
    uber_signer.ensure()
    uber_signer.sign(apk_path, output_path, keystore)
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
        uber_signer.ensure_debug_keystore(keystore)

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
    - AndroidManifest.xml: <meta-data android:resource="@null"/> elements lose
      the resource value during apktool decompile/recompile, producing binary
      XML that Android rejects with INSTALL_PARSE_FAILED_MANIFEST_MALFORMED.
      Remove these elements since @null means "no resource" anyway.
    """
    locale_config = work_dir / "res" / "xml" / "_generated_res_locale_config.xml"
    if locale_config.exists():
        content = locale_config.read_text()
        if "android:defaultLocale" in content:
            fixed = re.sub(r'\s+android:defaultLocale="[^"]*"', "", content)
            locale_config.write_text(fixed)

    manifest = work_dir / "AndroidManifest.xml"
    if manifest.exists():
        content = manifest.read_text()
        if 'android:resource="@null"' in content:
            fixed = re.sub(
                r'\s*<meta-data[^>]*android:resource="@null"[^/]*/>\s*',
                "\n",
                content,
            )
            manifest.write_text(fixed)
