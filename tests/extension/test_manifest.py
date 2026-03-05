"""Tests for native messaging host manifest generation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cli.commands.extension.manifest import (
    HOST_NAME,
    MANIFEST_FILENAME,
    generate_manifest,
)


class TestGenerateManifest:
    def test_structure(self) -> None:
        m = generate_manifest("abcdef1234567890", "/usr/local/bin/spectral-host.sh")
        assert m["name"] == HOST_NAME
        assert m["type"] == "stdio"
        assert m["path"] == "/usr/local/bin/spectral-host.sh"
        assert m["allowed_origins"] == ["chrome-extension://abcdef1234567890/"]

    def test_different_extension_id(self) -> None:
        m = generate_manifest("xyz", "/bin/host")
        assert m["allowed_origins"] == ["chrome-extension://xyz/"]


class TestHostManifestPaths:
    @patch("cli.commands.extension.manifest.sys")
    def test_linux_chrome(self, mock_sys: object, tmp_path: Path) -> None:
        import cli.commands.extension.manifest as mod

        mock_sys.platform = "linux"  # type: ignore[attr-defined]
        with patch.object(Path, "home", return_value=tmp_path):
            # Create the parent dir so auto-detect finds it
            (tmp_path / ".config" / "google-chrome").mkdir(parents=True)
            paths = mod.host_manifest_paths("chrome")
        assert len(paths) == 1
        assert paths[0].name == MANIFEST_FILENAME
        assert "google-chrome" in str(paths[0])

    @patch("cli.commands.extension.manifest.sys")
    def test_linux_auto_detect(self, mock_sys: object, tmp_path: Path) -> None:
        import cli.commands.extension.manifest as mod

        mock_sys.platform = "linux"  # type: ignore[attr-defined]
        with patch.object(Path, "home", return_value=tmp_path):
            # Create dirs for chrome and brave only
            (tmp_path / ".config" / "google-chrome").mkdir(parents=True)
            (tmp_path / ".config" / "BraveSoftware" / "Brave-Browser").mkdir(parents=True)
            paths = mod.host_manifest_paths(None)
        assert len(paths) == 2
        browser_names = [str(p) for p in paths]
        assert any("google-chrome" in s for s in browser_names)
        assert any("BraveSoftware" in s for s in browser_names)

    @patch("cli.commands.extension.manifest.sys")
    def test_darwin_chrome(self, mock_sys: object, tmp_path: Path) -> None:
        import cli.commands.extension.manifest as mod

        mock_sys.platform = "darwin"  # type: ignore[attr-defined]
        with patch.object(Path, "home", return_value=tmp_path):
            paths = mod.host_manifest_paths("chrome")
        assert len(paths) == 1
        assert "Google/Chrome" in str(paths[0])

    @patch("cli.commands.extension.manifest.sys")
    def test_unknown_browser(self, mock_sys: object, tmp_path: Path) -> None:
        import cli.commands.extension.manifest as mod

        mock_sys.platform = "linux"  # type: ignore[attr-defined]
        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(ValueError, match="Unknown browser"):
                mod.host_manifest_paths("firefox")
