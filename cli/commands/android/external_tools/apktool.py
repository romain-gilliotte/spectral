"""Wrapper around apktool for APK decompilation and recompilation."""

from __future__ import annotations

from pathlib import Path

from cli.commands.android.external_tools.bootstrap import (
    TOOLS_DIR,
    check_java,
    download_jar,
)
from cli.helpers.subprocess import run_cmd

_VERSION = "2.11.1"
_URL = f"https://github.com/iBotPeaches/Apktool/releases/download/v{_VERSION}/apktool_{_VERSION}.jar"
_JAR = TOOLS_DIR / "apktool.jar"


def ensure() -> None:
    """Download apktool on first use. Requires Java."""
    check_java()
    download_jar(_URL, _JAR, "apktool")


def _cmd() -> list[str]:
    return ["java", "-jar", str(_JAR)]


def decompile(apk_path: Path, output_dir: Path) -> None:
    """Decompile an APK using apktool (--no-src for speed)."""
    run_cmd(
        [*_cmd(), "d", "--no-src", str(apk_path), "-o", str(output_dir), "-f"],
        "Decompiling APK",
        timeout=300,
    )


def build(work_dir: Path, output_apk: Path) -> None:
    """Recompile a decompiled APK directory."""
    run_cmd(
        [*_cmd(), "b", str(work_dir), "-o", str(output_apk)],
        "Recompiling APK",
        timeout=300,
    )
