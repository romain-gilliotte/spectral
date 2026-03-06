"""Wrapper around uber-apk-signer for APK signing."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

from cli.commands.android.external_tools.bootstrap import (
    TOOLS_DIR,
    check_java,
    download_jar,
)
from cli.helpers.subprocess import run_cmd

_VERSION = "1.3.0"
_URL = f"https://github.com/patrickfav/uber-apk-signer/releases/download/v{_VERSION}/uber-apk-signer-{_VERSION}.jar"
_JAR = TOOLS_DIR / "uber-apk-signer.jar"


def ensure() -> None:
    """Download uber-apk-signer on first use. Requires Java."""
    check_java()
    download_jar(_URL, _JAR, "uber-apk-signer")


def _cmd() -> list[str]:
    return ["java", "-jar", str(_JAR)]


def ensure_debug_keystore(keystore_path: Path) -> None:
    """Create a debug keystore if it doesn't exist."""
    if keystore_path.exists():
        return
    run_cmd(
        [
            "keytool",
            "-genkey",
            "-v",
            "-keystore",
            str(keystore_path),
            "-alias",
            "debug",
            "-keyalg",
            "RSA",
            "-keysize",
            "2048",
            "-validity",
            "10000",
            "-storepass",
            "android",
            "-keypass",
            "android",
            "-dname",
            "CN=Debug,O=Debug,C=US",
        ],
        "Generating debug keystore",
    )


def sign(unsigned_apk: Path, output_path: Path, keystore: Path) -> None:
    """Sign an APK with v1+v2+v3 schemes using uber-apk-signer."""
    with tempfile.TemporaryDirectory(prefix="apk_sign_") as sign_dir:
        staging = Path(sign_dir) / "input" / unsigned_apk.name
        staging.parent.mkdir()
        shutil.copy2(unsigned_apk, staging)

        run_cmd(
            [
                *_cmd(),
                "--apks",
                str(staging.parent),
                "--ks",
                str(keystore),
                "--ksPass",
                "android",
                "--ksAlias",
                "debug",
                "--ksKeyPass",
                "android",
                "--out",
                str(Path(sign_dir) / "out"),
                "--allowResign",
            ],
            "Signing APK",
            timeout=300,
        )

        signed_files = list((Path(sign_dir) / "out").glob("*-aligned-signed.apk"))
        if not signed_files:
            raise RuntimeError("uber-apk-signer produced no output")
        shutil.copy2(signed_files[0], output_path)
