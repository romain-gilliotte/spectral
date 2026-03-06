"""Bootstrap utilities for downloading and verifying external tool dependencies."""

from __future__ import annotations

from pathlib import Path
import shutil
import urllib.request

TOOLS_DIR = Path(__file__).resolve().parents[4] / "tools"


def check_java() -> None:
    """Verify that java is installed and accessible.

    Raises RuntimeError with installation instructions if not found.
    """
    if shutil.which("java") is None:
        raise RuntimeError("java not found. Install Java JDK 11+.")


def download_jar(url: str, dest: Path, name: str) -> None:
    """Download a JAR file if it doesn't already exist."""
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download {name}: {e}")
