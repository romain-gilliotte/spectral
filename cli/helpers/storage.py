"""Managed storage for Spectral apps and captures.

Layout::

    ~/.local/share/spectral/          # SPECTRAL_HOME overrides
    └── apps/
        └── <name>/
            ├── app.json              # AppMeta
            └── captures/
                └── <timestamp>_<source>_<id-prefix>/
                    ├── manifest.json
                    ├── traces/ ...
                    ├── ws/ ...
                    ├── contexts/ ...
                    └── timeline.json
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re

from cli.commands.capture.loader import load_bundle, write_bundle_dir
from cli.commands.capture.types import CaptureBundle
from cli.formats.app_meta import AppMeta
from cli.formats.capture_bundle import CaptureManifest


class DuplicateCaptureError(Exception):
    """Raised when a capture with the same ID already exists in storage."""

    def __init__(self, capture_id: str, cap_dir: Path) -> None:
        self.capture_id = capture_id
        self.cap_dir = cap_dir
        super().__init__(f"Capture already exists: {capture_id} at {cap_dir}")


def store_root() -> Path:
    """Return the root storage directory."""
    env = os.environ.get("SPECTRAL_HOME")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "spectral"


def app_dir(name: str) -> Path:
    """Return the directory for an app."""
    return store_root() / "apps" / name


def slugify(name: str) -> str:
    """Convert a display name to a filesystem-safe slug.

    ``"EDF Portal"`` → ``"edf-portal"``
    """
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "app"


def capture_dirname(manifest: CaptureManifest) -> str:
    """Generate a capture directory name from a manifest.

    Format: ``{timestamp}_{source}_{id-prefix}``
    """
    # Parse created_at to a filesystem-safe timestamp
    ts = manifest.created_at
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        dt = dt.astimezone(timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc)
    ts_str = dt.strftime("%Y-%m-%dT%H-%M-%S")

    source = "proxy" if manifest.capture_method == "proxy" else "ext"
    id_prefix = manifest.capture_id[:8]
    return f"{ts_str}_{source}_{id_prefix}"


def ensure_app(name: str, display_name: str | None = None) -> Path:
    """Create app dir and app.json if needed. Idempotent.

    Updates ``updated_at`` on every call.
    """
    d = app_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "captures").mkdir(exist_ok=True)

    meta_path = d / "app.json"
    now = datetime.now(timezone.utc).isoformat()

    if meta_path.exists():
        meta = AppMeta.model_validate_json(meta_path.read_text())
        meta.updated_at = now
    else:
        meta = AppMeta(
            name=name,
            display_name=display_name or name,
            created_at=now,
            updated_at=now,
        )

    meta_path.write_text(meta.model_dump_json(indent=2))
    return d


def import_capture(zip_path: str | Path, app_name: str) -> Path:
    """Load a ZIP bundle and write it as flat files into managed storage.

    Returns the capture directory path.
    """
    bundle = load_bundle(zip_path)
    return store_capture(bundle, app_name)


def store_capture(bundle: CaptureBundle, app_name: str) -> Path:
    """Write a CaptureBundle as flat files into managed storage.

    Returns the capture directory path.

    Raises ``DuplicateCaptureError`` if a capture with the same ``capture_id``
    already exists under the app.
    """
    ensure_app(app_name)

    # Check all existing captures for duplicate capture_id
    capture_id = bundle.manifest.capture_id
    for existing in list_captures(app_name):
        existing_manifest = CaptureManifest.model_validate_json(
            (existing / "manifest.json").read_text()
        )
        if existing_manifest.capture_id == capture_id:
            raise DuplicateCaptureError(capture_id, existing)

    dirname = capture_dirname(bundle.manifest)
    cap_dir = app_dir(app_name) / "captures" / dirname
    write_bundle_dir(bundle, cap_dir)
    return cap_dir


def list_apps() -> list[AppMeta]:
    """Return all apps from app.json files, sorted by name."""
    apps_dir = store_root() / "apps"
    if not apps_dir.is_dir():
        return []
    result: list[AppMeta] = []
    for d in sorted(apps_dir.iterdir()):
        meta_path = d / "app.json"
        if meta_path.is_file():
            result.append(AppMeta.model_validate_json(meta_path.read_text()))
    return result


def list_captures(app_name: str) -> list[Path]:
    """Return sorted capture dirs for an app (oldest first)."""
    caps_dir = app_dir(app_name) / "captures"
    if not caps_dir.is_dir():
        return []
    return sorted(
        d for d in caps_dir.iterdir() if d.is_dir() and (d / "manifest.json").exists()
    )


def latest_capture(app_name: str) -> Path | None:
    """Return the most recent capture dir, or None."""
    caps = list_captures(app_name)
    return caps[-1] if caps else None


def resolve_app(name: str) -> Path:
    """Validate that an app exists and return its directory.

    Raises ``click.ClickException`` if not found.
    """
    import click

    d = app_dir(name)
    if not (d / "app.json").is_file():
        raise click.ClickException(f"App '{name}' not found. Run 'spectral capture list' to see known apps.")
    return d
