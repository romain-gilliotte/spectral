"""Tests for catalog-related storage functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.formats.catalog import CatalogToken, ToolStats
from cli.helpers.storage import (
    delete_catalog_token,
    ensure_app,
    load_catalog_token,
    load_stats,
    record_tool_call,
    write_catalog_token,
    write_stats,
)


class TestCatalogTokenStorage:
    def test_load_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        assert load_catalog_token() is None

    def test_write_and_load(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        token = CatalogToken(access_token="ghu_abc", username="testuser")
        write_catalog_token(token)

        loaded = load_catalog_token()
        assert loaded is not None
        assert loaded.access_token == "ghu_abc"
        assert loaded.username == "testuser"

    def test_delete_existing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        write_catalog_token(CatalogToken(access_token="tok", username="u"))
        assert delete_catalog_token() is True
        assert load_catalog_token() is None

    def test_delete_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        assert delete_catalog_token() is False


class TestStatsStorage:
    def test_load_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        stats = load_stats("myapp")
        assert stats.root == {}

    def test_write_and_load(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from cli.formats.catalog import ToolExecStats

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")
        stats = ToolStats(
            {"search": ToolExecStats(call_count=5, success_count=4, error_count=1)}
        )
        write_stats("myapp", stats)

        loaded = load_stats("myapp")
        assert loaded.root["search"].call_count == 5
        assert loaded.root["search"].success_count == 4

    def test_record_tool_call_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")

        record_tool_call("myapp", "search", 200, 150.0)
        stats = load_stats("myapp")
        entry = stats.root["search"]
        assert entry.call_count == 1
        assert entry.success_count == 1
        assert entry.error_count == 0
        assert entry.last_status_code == 200
        assert entry.avg_latency_ms == 150.0

    def test_record_tool_call_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")

        record_tool_call("myapp", "search", 500, 200.0)
        stats = load_stats("myapp")
        entry = stats.root["search"]
        assert entry.call_count == 1
        assert entry.success_count == 0
        assert entry.error_count == 1

    def test_record_tool_call_none_status(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")

        record_tool_call("myapp", "search", None, 0.0)
        stats = load_stats("myapp")
        entry = stats.root["search"]
        assert entry.error_count == 1
        assert entry.last_status_code is None

    def test_record_tool_call_accumulates(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")

        record_tool_call("myapp", "search", 200, 100.0)
        record_tool_call("myapp", "search", 200, 200.0)
        stats = load_stats("myapp")
        entry = stats.root["search"]
        assert entry.call_count == 2
        assert entry.success_count == 2
        assert entry.avg_latency_ms == 150.0  # (100 + 200) / 2
