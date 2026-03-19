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
import time

import click

from cli.commands.capture.loader import load_bundle, load_bundle_dir, write_bundle_dir
from cli.commands.capture.types import CaptureBundle, merge_bundles
from cli.formats.app_meta import AppMeta
from cli.formats.capture_bundle import CaptureManifest
from cli.formats.catalog import CatalogToken, ToolExecStats, ToolStats
from cli.formats.config import Config
from cli.formats.mcp_tool import TokenState, ToolDefinition

APP_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def validate_app_name(name: str) -> None:
    """Validate an app name (local or catalog).

    Local names must match ``[a-z0-9]+(-[a-z0-9]+)*``.
    Catalog names use ``owner__app`` where both segments match the same pattern.

    Raises ``click.ClickException`` on invalid names.
    """
    if not name:
        raise click.ClickException("App name cannot be empty.")

    if "__" in name:
        parts = name.split("__", 1)
        if not all(APP_NAME_RE.match(p) for p in parts):
            raise click.ClickException(
                f"Invalid catalog app name '{name}'. "
                "Both segments around '__' must be lowercase alphanumeric with single hyphens "
                "(e.g. 'owner__my-app')."
            )
    else:
        if not APP_NAME_RE.match(name):
            raise click.ClickException(
                f"Invalid app name '{name}'. "
                "Use lowercase letters, digits, and single hyphens "
                "(e.g. 'my-app'). No leading/trailing hyphens."
            )

    # Safety net: ensure the resolved path stays inside the apps directory
    apps_root = store_root() / "apps"
    resolved = (apps_root / name).resolve()
    if not resolved.is_relative_to(apps_root.resolve()):
        raise click.ClickException(f"Invalid app name '{name}': path traversal detected.")


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
    validate_app_name(name)
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
    validate_app_name(name)
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


def store_capture(
    bundle: CaptureBundle, app_name: str, *, display_name: str | None = None
) -> Path:
    """Write a CaptureBundle as flat files into managed storage.

    Returns the capture directory path.

    Raises ``DuplicateCaptureError`` if a capture with the same ``capture_id``
    already exists under the app.
    """
    ensure_app(app_name, display_name=display_name)

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
    d = app_dir(name)
    if not (d / "app.json").is_file():
        raise click.ClickException(f"App '{name}' not found. Run 'spectral capture list' to see known apps.")
    return d


def load_app_bundle(app_name: str) -> CaptureBundle:
    """Load all captures for an app and merge them into a single bundle.

    Raises ``click.ClickException`` if the app doesn't exist or has no captures.
    """
    resolve_app(app_name)
    cap_dirs = list_captures(app_name)
    if not cap_dirs:
        raise click.ClickException(f"App '{app_name}' has no captures.")
    bundles = [load_bundle_dir(d) for d in cap_dirs]
    return merge_bundles(bundles)


# ---------------------------------------------------------------------------
# MCP tool and auth storage
# ---------------------------------------------------------------------------


def tools_dir(app_name: str) -> Path:
    """Return the tools directory for an app."""
    return app_dir(app_name) / "tools"


def list_tools(app_name: str) -> list[ToolDefinition]:
    """Load all tool definitions for an app, sorted by name."""
    td = tools_dir(app_name)
    if not td.is_dir():
        return []
    result: list[ToolDefinition] = []
    for f in sorted(td.iterdir()):
        if f.suffix == ".json" and f.is_file():
            try:
                result.append(ToolDefinition.model_validate_json(f.read_text()))
            except Exception as exc:
                click.echo(f"Warning: skipping {f.name} for app '{app_name}': {exc}", err=True)
    return result


def write_tools(app_name: str, tools: list[ToolDefinition]) -> None:
    """Clear the tools directory and write new tool JSON files."""
    td = tools_dir(app_name)
    if td.is_dir():
        for f in td.iterdir():
            if f.suffix == ".json" and f.is_file():
                f.unlink()
    td.mkdir(parents=True, exist_ok=True)
    for tool in tools:
        path = td / f"{tool.name}.json"
        path.write_text(tool.model_dump_json(indent=2))


def load_token(app_name: str) -> TokenState | None:
    """Read token.json for an app, or None if missing."""
    token_path = app_dir(app_name) / "token.json"
    if not token_path.is_file():
        return None
    return TokenState.model_validate_json(token_path.read_text())


def write_token(app_name: str, token: TokenState) -> None:
    """Write token.json for an app."""
    token_path = app_dir(app_name) / "token.json"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token.model_dump_json(indent=2))


def delete_token(app_name: str) -> bool:
    """Delete token.json for an app. Returns True if a token was removed."""
    path = app_dir(app_name) / "token.json"
    if path.is_file():
        path.unlink()
        return True
    return False


def auth_script_path(app_name: str) -> Path:
    """Return the path to the auth_acquire.py script for an app."""
    return app_dir(app_name) / "auth_acquire.py"


def config_path() -> Path:
    """Return the path to config.json."""
    return store_root() / "config.json"


def load_config() -> Config | None:
    """Read config.json, or ``None`` if not set."""
    path = config_path()
    if not path.is_file():
        return None
    return Config.model_validate_json(path.read_text())


def write_config(config: Config) -> None:
    """Write config.json to managed storage."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2) + "\n")


def load_app_meta(app_name: str) -> AppMeta:
    """Load app.json for an app.

    Raises ``click.ClickException`` if the app doesn't exist.
    """
    meta_path = app_dir(app_name) / "app.json"
    if not meta_path.is_file():
        raise click.ClickException(f"App '{app_name}' not found.")
    return AppMeta.model_validate_json(meta_path.read_text())


def load_catalog_token() -> CatalogToken | None:
    """Read catalog_token.json, or ``None`` if not logged in."""
    path = store_root() / "catalog_token.json"
    if not path.is_file():
        return None
    return CatalogToken.model_validate_json(path.read_text())


def write_catalog_token(token: CatalogToken) -> None:
    """Write catalog_token.json to managed storage."""
    path = store_root() / "catalog_token.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.model_dump_json(indent=2))


def delete_catalog_token() -> bool:
    """Delete catalog_token.json. Returns True if a token was removed."""
    path = store_root() / "catalog_token.json"
    if path.is_file():
        path.unlink()
        return True
    return False


def load_stats(app_name: str) -> ToolStats:
    """Read stats.json for an app, returning empty stats if missing."""
    stats_path = app_dir(app_name) / "stats.json"
    if not stats_path.is_file():
        return ToolStats({})
    return ToolStats.model_validate_json(stats_path.read_text())


def write_stats(app_name: str, stats: ToolStats) -> None:
    """Write stats.json for an app."""
    stats_path = app_dir(app_name) / "stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(stats.model_dump_json(indent=2))


def record_tool_call(
    app_name: str, tool_name: str, status_code: int | None, latency_ms: float
) -> None:
    """Record a single tool execution in stats.json."""
    stats = load_stats(app_name)
    entry = stats.root.get(tool_name, ToolExecStats())
    prev_total = entry.call_count
    entry.call_count += 1
    if status_code is not None and 200 <= status_code < 400:
        entry.success_count += 1
    else:
        entry.error_count += 1
    entry.last_called_at = time.time()
    entry.last_status_code = status_code
    # Running average
    if prev_total > 0:
        entry.avg_latency_ms = (
            entry.avg_latency_ms * prev_total + latency_ms
        ) / entry.call_count
    else:
        entry.avg_latency_ms = latency_ms
    stats.root[tool_name] = entry
    write_stats(app_name, stats)


def update_app_meta(app_name: str, **kwargs: object) -> None:
    """Update fields of app.json for an app."""
    meta = load_app_meta(app_name)
    for key, value in kwargs.items():
        if hasattr(meta, key):
            setattr(meta, key, value)
    meta_path = app_dir(app_name) / "app.json"
    meta_path.write_text(meta.model_dump_json(indent=2))
