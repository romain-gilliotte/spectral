"""Tests for catalog Pydantic models."""

from __future__ import annotations

from cli.formats.app_meta import AppMeta
from cli.formats.catalog import (
    CatalogManifest,
    CatalogSource,
    CatalogToken,
    ToolExecStats,
    ToolStats,
)


class TestCatalogToken:
    def test_roundtrip(self) -> None:
        token = CatalogToken(access_token="ghu_abc123", username="romain")
        data = token.model_dump_json()
        loaded = CatalogToken.model_validate_json(data)
        assert loaded.access_token == "ghu_abc123"
        assert loaded.username == "romain"


class TestCatalogManifest:
    def test_roundtrip(self) -> None:
        manifest = CatalogManifest(
            display_name="Planity",
            description="Book appointments",
            spectral_version="0.3.1",
        )
        data = manifest.model_dump_json()
        loaded = CatalogManifest.model_validate_json(data)
        assert loaded.display_name == "Planity"


class TestCatalogSource:
    def test_roundtrip(self) -> None:
        source = CatalogSource(username="romain", app_name="planity-com")
        data = source.model_dump_json()
        loaded = CatalogSource.model_validate_json(data)
        assert loaded.username == "romain"
        assert loaded.app_name == "planity-com"


class TestToolExecStats:
    def test_defaults(self) -> None:
        stats = ToolExecStats()
        assert stats.call_count == 0
        assert stats.success_count == 0
        assert stats.error_count == 0
        assert stats.last_called_at is None
        assert stats.avg_latency_ms == 0.0


class TestToolStats:
    def test_empty(self) -> None:
        stats = ToolStats({})
        assert stats.root == {}

    def test_roundtrip(self) -> None:
        stats = ToolStats(
            {"search": ToolExecStats(call_count=10, success_count=9, error_count=1)}
        )
        data = stats.model_dump_json()
        loaded = ToolStats.model_validate_json(data)
        assert loaded.root["search"].call_count == 10

    def test_flat_json_format(self) -> None:
        """stats.json must serialize as a flat dict, not wrapped in 'tools'."""
        import json

        stats = ToolStats(
            {"search": ToolExecStats(call_count=5, success_count=4, error_count=1)}
        )
        data = json.loads(stats.model_dump_json())
        assert "tools" not in data
        assert "search" in data
        assert data["search"]["call_count"] == 5


class TestAppMetaCatalogSource:
    def test_catalog_source_optional(self) -> None:
        meta = AppMeta(name="test", created_at="now", updated_at="now")
        assert meta.catalog_source is None

    def test_catalog_source_roundtrip(self) -> None:
        meta = AppMeta(
            name="test",
            created_at="now",
            updated_at="now",
            catalog_source=CatalogSource(username="romain", app_name="planity-com"),
        )
        data = meta.model_dump_json()
        loaded = AppMeta.model_validate_json(data)
        assert loaded.catalog_source is not None
        assert loaded.catalog_source.username == "romain"
