"""Tests for managed storage and flat-directory bundle I/O."""

from __future__ import annotations

from pathlib import Path

import click
import pytest

from cli.commands.capture.loader import load_bundle_dir, write_bundle_dir
from cli.commands.capture.types import CaptureBundle
from cli.formats.app_meta import AppMeta
from cli.formats.capture_bundle import (
    AppInfo,
    BrowserInfo,
    CaptureManifest,
    CaptureStats,
)
from cli.formats.mcp_tool import TokenState, ToolDefinition, ToolRequest
from cli.helpers.storage import (
    APP_NAME_RE,
    DuplicateCaptureError,
    auth_script_path,
    capture_dirname,
    ensure_app,
    import_capture,
    latest_capture,
    list_apps,
    list_captures,
    list_tools,
    load_app_meta,
    load_config,
    load_token,
    resolve_app,
    slugify,
    store_capture,
    store_root,
    tools_dir,
    update_app_meta,
    validate_app_name,
    write_config,
    write_token,
    write_tools,
)

# ---------------------------------------------------------------------------
# Flat-directory bundle roundtrip
# ---------------------------------------------------------------------------


class TestBundleDirRoundtrip:
    def test_write_and_load(
        self, sample_bundle: CaptureBundle, tmp_path: Path
    ) -> None:
        d = tmp_path / "cap"
        write_bundle_dir(sample_bundle, d)

        loaded = load_bundle_dir(d)
        assert loaded.manifest.capture_id == sample_bundle.manifest.capture_id
        assert len(loaded.traces) == len(sample_bundle.traces)
        assert len(loaded.ws_connections) == len(sample_bundle.ws_connections)
        assert len(loaded.contexts) == len(sample_bundle.contexts)
        assert len(loaded.timeline.events) == len(sample_bundle.timeline.events)

    def test_trace_bodies_preserved(
        self, sample_bundle: CaptureBundle, tmp_path: Path
    ) -> None:
        d = tmp_path / "cap"
        write_bundle_dir(sample_bundle, d)
        loaded = load_bundle_dir(d)

        for orig, loaded_trace in zip(sample_bundle.traces, loaded.traces):
            assert loaded_trace.request_body == orig.request_body
            assert loaded_trace.response_body == orig.response_body

    def test_ws_messages_preserved(
        self, sample_bundle: CaptureBundle, tmp_path: Path
    ) -> None:
        d = tmp_path / "cap"
        write_bundle_dir(sample_bundle, d)
        loaded = load_bundle_dir(d)

        assert len(loaded.ws_connections) == 1
        ws = loaded.ws_connections[0]
        assert ws.meta.id == "ws_0001"
        assert len(ws.messages) == 2
        assert ws.messages[0].payload == b'{"type":"subscribe","id":"1"}'

    def test_empty_bundle(self, tmp_path: Path) -> None:
        bundle = CaptureBundle(
            manifest=CaptureManifest(
                capture_id="empty",
                created_at="2026-01-01T00:00:00Z",
                app=AppInfo(name="Empty", base_url="http://localhost", title="Empty"),
                browser=BrowserInfo(name="Chrome", version="1.0"),
                duration_ms=0,
                stats=CaptureStats(),
            ),
        )
        d = tmp_path / "cap"
        write_bundle_dir(bundle, d)
        loaded = load_bundle_dir(d)

        assert loaded.manifest.capture_id == "empty"
        assert len(loaded.traces) == 0

    def test_binary_body_roundtrip(self, tmp_path: Path) -> None:
        from tests.conftest import make_trace

        binary_body = bytes(range(256))
        trace = make_trace(
            "t_0001", "POST", "http://localhost/bin", 200,
            timestamp=1000, request_body=binary_body, response_body=binary_body,
        )
        bundle = CaptureBundle(
            manifest=CaptureManifest(
                capture_id="bin",
                created_at="2026-01-01T00:00:00Z",
                app=AppInfo(name="Bin", base_url="http://localhost", title="Bin"),
                duration_ms=0,
                stats=CaptureStats(trace_count=1),
            ),
            traces=[trace],
        )
        d = tmp_path / "cap"
        write_bundle_dir(bundle, d)
        loaded = load_bundle_dir(d)
        assert loaded.traces[0].request_body == binary_body
        assert loaded.traces[0].response_body == binary_body


# ---------------------------------------------------------------------------
# Slugify + capture dirname
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic(self) -> None:
        assert slugify("EDF Portal") == "edf-portal"

    def test_special_chars(self) -> None:
        assert slugify("My App (v2)") == "my-app-v2"

    def test_empty(self) -> None:
        assert slugify("") == "app"

    def test_already_slug(self) -> None:
        assert slugify("my-app") == "my-app"


class TestCaptureDirname:
    def test_extension(self) -> None:
        m = CaptureManifest(
            capture_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            created_at="2026-02-13T15:30:00Z",
            app=AppInfo(name="EDF", base_url="https://edf.fr", title="EDF"),
            duration_ms=1000,
            stats=CaptureStats(),
            capture_method="chrome_extension",
        )
        assert capture_dirname(m) == "2026-02-13T15-30-00_ext_a1b2c3d4"

    def test_proxy(self) -> None:
        m = CaptureManifest(
            capture_id="deadbeef-0000-0000-0000-000000000000",
            created_at="2026-03-01T10:05:30Z",
            app=AppInfo(name="App", base_url="https://app.com", title="App"),
            duration_ms=500,
            stats=CaptureStats(),
            capture_method="proxy",
        )
        assert capture_dirname(m) == "2026-03-01T10-05-30_proxy_deadbeef"

    def test_non_utc_normalized(self) -> None:
        m = CaptureManifest(
            capture_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            created_at="2026-02-13T17:30:00+02:00",
            app=AppInfo(name="EDF", base_url="https://edf.fr", title="EDF"),
            duration_ms=1000,
            stats=CaptureStats(),
        )
        assert capture_dirname(m) == "2026-02-13T15-30-00_ext_a1b2c3d4"


# ---------------------------------------------------------------------------
# App name validation
# ---------------------------------------------------------------------------


class TestValidateAppName:
    @pytest.mark.parametrize(
        "name",
        ["my-app", "a", "app2", "romain__planity-com", "foo__bar-baz", "abc123"],
    )
    def test_valid_names(self, name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        validate_app_name(name)  # should not raise

    @pytest.mark.parametrize(
        "name",
        [
            "../etc",
            "MY-APP",
            "my_app",
            "toto__",
            "__app",
            "-app",
            "app-",
            "my--app",
            "",
            "a/b",
            "..",
            "App",
            "foo__BAR",
        ],
    )
    def test_invalid_names(self, name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        with pytest.raises(click.ClickException):
            validate_app_name(name)

    def test_regex_no_double_hyphens(self) -> None:
        assert APP_NAME_RE.match("my--app") is None

    def test_regex_no_leading_hyphen(self) -> None:
        assert APP_NAME_RE.match("-app") is None

    def test_regex_no_trailing_hyphen(self) -> None:
        assert APP_NAME_RE.match("app-") is None


# ---------------------------------------------------------------------------
# Storage functions (use SPECTRAL_HOME → tmp_path)
# ---------------------------------------------------------------------------


class TestStorageFunctions:
    def test_store_root_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPECTRAL_HOME", raising=False)
        root = store_root()
        assert root == Path.home() / ".local" / "share" / "spectral"

    def test_store_root_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path / "custom"))
        assert store_root() == tmp_path / "custom"

    def test_ensure_app_creates_structure(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        d = ensure_app("edf", "EDF")
        assert (d / "app.json").is_file()
        assert (d / "captures").is_dir()

        meta = AppMeta.model_validate_json((d / "app.json").read_text())
        assert meta.name == "edf"
        assert meta.display_name == "EDF"

    def test_ensure_app_idempotent(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("edf", "EDF")
        meta1 = AppMeta.model_validate_json(
            (tmp_path / "apps" / "edf" / "app.json").read_text()
        )
        ensure_app("edf")
        meta2 = AppMeta.model_validate_json(
            (tmp_path / "apps" / "edf" / "app.json").read_text()
        )
        assert meta2.name == "edf"
        assert meta2.display_name == "EDF"  # preserved
        assert meta2.created_at == meta1.created_at

    def test_store_and_list_captures(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        cap_dir = store_capture(sample_bundle, "myapp")
        assert cap_dir.is_dir()
        assert (cap_dir / "manifest.json").is_file()

        caps = list_captures("myapp")
        assert len(caps) == 1
        assert caps[0] == cap_dir

    def test_import_capture_from_zip(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.commands.capture.loader import write_bundle

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        zip_path = tmp_path / "upload.zip"
        write_bundle(sample_bundle, zip_path)

        cap_dir = import_capture(zip_path, "imported")
        assert cap_dir.is_dir()

        loaded = load_bundle_dir(cap_dir)
        assert loaded.manifest.capture_id == sample_bundle.manifest.capture_id
        assert len(loaded.traces) == len(sample_bundle.traces)

    def test_list_apps(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("alfa")
        ensure_app("bravo")
        apps = list_apps()
        assert len(apps) == 2
        assert apps[0].name == "alfa"
        assert apps[1].name == "bravo"

    def test_latest_capture(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        store_capture(sample_bundle, "myapp")
        latest = latest_capture("myapp")
        assert latest is not None
        assert (latest / "manifest.json").is_file()

    def test_latest_capture_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("empty")
        assert latest_capture("empty") is None

    def test_resolve_app_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import click

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        with pytest.raises(click.ClickException, match="not found"):
            resolve_app("nonexistent")

    def test_resolve_app_exists(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        d = resolve_app("myapp")
        assert d.is_dir()

    def test_store_capture_duplicate_raises(
        self, sample_bundle: CaptureBundle, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        store_capture(sample_bundle, "myapp")
        with pytest.raises(DuplicateCaptureError) as exc_info:
            store_capture(sample_bundle, "myapp")
        assert exc_info.value.capture_id == sample_bundle.manifest.capture_id


# ---------------------------------------------------------------------------
# MCP tool and auth storage
# ---------------------------------------------------------------------------


def _make_tool(name: str, description: str = "A tool") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        parameters={"type": "object", "properties": {}},
        request=ToolRequest(method="GET", url=f"https://api.example.com/{name}"),
    )


class TestToolStorage:
    def test_tools_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        td = tools_dir("myapp")
        assert td == tmp_path / "apps" / "myapp" / "tools"

    def test_list_tools_empty(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        assert list_tools("myapp") == []

    def test_write_and_list_tools(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        tools = [_make_tool("zeta"), _make_tool("alpha")]
        write_tools("myapp", tools)

        loaded = list_tools("myapp")
        assert len(loaded) == 2
        assert loaded[0].name == "alpha"  # sorted by name
        assert loaded[1].name == "zeta"

    def test_write_tools_clears_previous(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        write_tools("myapp", [_make_tool("old_tool")])
        assert len(list_tools("myapp")) == 1

        write_tools("myapp", [_make_tool("new_tool")])
        loaded = list_tools("myapp")
        assert len(loaded) == 1
        assert loaded[0].name == "new_tool"


    def test_list_tools_skips_invalid_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        write_tools("myapp", [_make_tool("good_tool")])
        # Write invalid JSON alongside the valid tool
        (tools_dir("myapp") / "bad_tool.json").write_text("{invalid json")

        loaded = list_tools("myapp")
        assert len(loaded) == 1
        assert loaded[0].name == "good_tool"
        captured = capsys.readouterr()
        assert "bad_tool.json" in captured.err

    def test_list_tools_skips_stale_schema(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        td = tools_dir("myapp")
        td.mkdir(parents=True, exist_ok=True)
        # Write a tool with old "path" field instead of "url"
        import json
        from typing import Any

        stale: dict[str, Any] = {
            "name": "stale_tool",
            "description": "A stale tool",
            "parameters": {"type": "object", "properties": {}},
            "request": {"method": "GET", "path": "/api/foo"},
        }
        (td / "stale_tool.json").write_text(json.dumps(stale))

        loaded = list_tools("myapp")
        assert len(loaded) == 0
        captured = capsys.readouterr()
        assert "stale_tool.json" in captured.err


class TestTokenStorage:
    def test_load_token_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        assert load_token("myapp") is None

    def test_write_and_load_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        token = TokenState(
            headers={"Authorization": "Bearer ey123"},
            refresh_token="rt_abc",
            expires_at=1700000000.0,
            obtained_at=1699990000.0,
        )
        write_token("myapp", token)
        loaded = load_token("myapp")
        assert loaded is not None
        assert loaded.headers == {"Authorization": "Bearer ey123"}
        assert loaded.refresh_token == "rt_abc"


class TestAuthScriptPath:
    def test_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        p = auth_script_path("myapp")
        assert p == tmp_path / "apps" / "myapp" / "auth_acquire.py"


class TestAppMetaFunctions:
    def test_load_app_meta(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp", "My App")
        meta = load_app_meta("myapp")
        assert meta.name == "myapp"
        assert meta.display_name == "My App"

    def test_load_app_meta_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import click

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        with pytest.raises(click.ClickException, match="not found"):
            load_app_meta("nonexistent")

    def test_update_app_meta(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        update_app_meta("myapp", base_urls=["https://api.example.com"])
        meta = load_app_meta("myapp")
        assert meta.base_urls == ["https://api.example.com"]

    def test_update_app_meta_preserves_fields(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp", "My App")
        update_app_meta("myapp", base_urls=["https://api.example.com"])
        meta = load_app_meta("myapp")
        assert meta.display_name == "My App"
        assert meta.base_urls == ["https://api.example.com"]


class TestConfigStorage:
    def test_load_config_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        assert load_config() is None

    def test_write_and_load_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from cli.formats.config import Config

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        write_config(Config(api_key="sk-ant-test-key"))
        config = load_config()
        assert config is not None
        assert config.api_key == "sk-ant-test-key"

    def test_config_default_model(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from cli.formats.config import Config

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        write_config(Config(api_key="sk-ant-test-key"))
        config = load_config()
        assert config is not None
        assert config.model == Config.model_fields["model"].default

    def test_config_custom_model(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from cli.formats.config import Config

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        write_config(Config(api_key="sk-ant-test-key", model="claude-opus-4-20250115"))
        config = load_config()
        assert config is not None
        assert config.model == "claude-opus-4-20250115"
