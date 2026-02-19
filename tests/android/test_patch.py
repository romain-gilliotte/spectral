"""Tests for APK patching (manifest, signing, directory patching)."""

from __future__ import annotations

from pathlib import Path
import textwrap
from unittest.mock import patch

import pytest

from cli.commands.android.patch import (
    NETWORK_SECURITY_CONFIG,
    PatchError,
    _patch_manifest,  # pyright: ignore[reportPrivateUsage]
    patch_apk_dir,
    sign_apk,
)


class TestPatchManifest:
    def test_adds_network_security_config(self, tmp_path: Path) -> None:
        manifest_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <manifest xmlns:android="http://schemas.android.com/apk/res/android"
                package="com.example.app">
                <application android:label="Test App">
                    <activity android:name=".MainActivity" />
                </application>
            </manifest>
        """)
        manifest_path = tmp_path / "AndroidManifest.xml"
        manifest_path.write_text(manifest_content)

        _patch_manifest(manifest_path)  # pyright: ignore[reportPrivateUsage]

        result = manifest_path.read_text()
        assert "networkSecurityConfig" in result
        assert "@xml/network_security_config" in result

    def test_existing_nsc_gets_overwritten(self, tmp_path: Path) -> None:
        manifest_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <manifest xmlns:android="http://schemas.android.com/apk/res/android"
                package="com.example.app">
                <application
                    android:label="Test App"
                    android:networkSecurityConfig="@xml/old_config">
                </application>
            </manifest>
        """)
        manifest_path = tmp_path / "AndroidManifest.xml"
        manifest_path.write_text(manifest_content)

        _patch_manifest(manifest_path)  # pyright: ignore[reportPrivateUsage]

        result = manifest_path.read_text()
        assert "@xml/network_security_config" in result
        assert "@xml/old_config" not in result

    def test_no_application_element_raises(self, tmp_path: Path) -> None:
        manifest_content = '<?xml version="1.0"?><manifest></manifest>'
        manifest_path = tmp_path / "AndroidManifest.xml"
        manifest_path.write_text(manifest_content)

        with pytest.raises(PatchError, match="No <application> element"):
            _patch_manifest(manifest_path)  # pyright: ignore[reportPrivateUsage]

    def test_network_security_config_content(self) -> None:
        """Verify the injected XML trusts both system and user CAs."""
        assert "system" in NETWORK_SECURITY_CONFIG
        assert "user" in NETWORK_SECURITY_CONFIG
        assert "trust-anchors" in NETWORK_SECURITY_CONFIG


class TestSignApk:
    def test_sign_apk_calls_signing_tool(self, tmp_path: Path) -> None:
        input_apk = tmp_path / "input.apk"
        input_apk.write_bytes(b"fake-apk")
        output_apk = tmp_path / "output.apk"
        keystore = tmp_path / "debug.keystore"
        keystore.write_bytes(b"fake-keystore")

        with patch("cli.commands.android.patch._ensure_tools"):
            with patch("cli.commands.android.patch._sign_apk") as mock_sign:
                result = sign_apk(input_apk, output_apk, keystore)
                mock_sign.assert_called_once_with(input_apk, output_apk, keystore)
                assert result == output_apk


class TestPatchApkDir:
    def test_patches_base_and_resigns_splits(self, tmp_path: Path) -> None:
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "base.apk").write_bytes(b"base-data")
        (input_dir / "split_config.arm64_v8a.apk").write_bytes(b"split1")
        (input_dir / "split_config.fr.apk").write_bytes(b"split2")
        output_dir = tmp_path / "output"

        with patch("cli.commands.android.patch._ensure_tools"):
            with patch("cli.commands.android.patch._ensure_debug_keystore"):
                with patch("cli.commands.android.patch.patch_apk") as mock_patch:
                    with patch("cli.commands.android.patch.sign_apk") as mock_sign:

                        def fake_patch(apk: Path, out: Path, keystore: Path) -> Path:
                            out.parent.mkdir(parents=True, exist_ok=True)
                            out.write_bytes(b"patched")
                            return out

                        def fake_sign(apk: Path, out: Path, ks: Path) -> Path:
                            out.write_bytes(b"signed")
                            return out

                        mock_patch.side_effect = fake_patch
                        mock_sign.side_effect = fake_sign

                        result = patch_apk_dir(input_dir, output_dir)

        assert result == output_dir
        assert result.is_dir()
        # patch_apk called for base
        assert mock_patch.call_count == 1
        base_call = mock_patch.call_args
        assert base_call[0][0] == input_dir / "base.apk"
        assert base_call[0][1] == output_dir / "base.apk"
        assert base_call[1]["keystore"] is not None
        # sign_apk called for splits
        assert mock_sign.call_count == 2
        signed_names = {call[0][0].name for call in mock_sign.call_args_list}
        assert signed_names == {"split_config.arm64_v8a.apk", "split_config.fr.apk"}

    def test_uses_first_apk_when_no_base(self, tmp_path: Path) -> None:
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        # No base.apk, only splits
        (input_dir / "app.apk").write_bytes(b"app-data")
        (input_dir / "split.apk").write_bytes(b"split-data")
        output_dir = tmp_path / "output"

        with patch("cli.commands.android.patch._ensure_tools"):
            with patch("cli.commands.android.patch._ensure_debug_keystore"):
                with patch("cli.commands.android.patch.patch_apk") as mock_patch:
                    with patch("cli.commands.android.patch.sign_apk") as mock_sign:

                        def fake_patch_fn(apk: Path, out: Path, keystore: Path) -> Path:
                            out.parent.mkdir(parents=True, exist_ok=True)
                            out.write_bytes(b"patched")
                            return out

                        def fake_sign_fn(apk: Path, out: Path, ks: Path) -> Path:
                            out.write_bytes(b"signed")
                            return out

                        mock_patch.side_effect = fake_patch_fn
                        mock_sign.side_effect = fake_sign_fn

                        patch_apk_dir(input_dir, output_dir)

        # First sorted APK (app.apk) used as base
        patched_apk = mock_patch.call_args[0][0]
        assert patched_apk.name == "app.apk"
        # split.apk re-signed
        assert mock_sign.call_count == 1
        assert mock_sign.call_args[0][0].name == "split.apk"

    def test_empty_dir_raises(self, tmp_path: Path) -> None:
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        with pytest.raises(PatchError, match="No .apk files found"):
            patch_apk_dir(input_dir, output_dir)

    def test_all_apks_share_keystore(self, tmp_path: Path) -> None:
        """All APKs should be signed with the same keystore."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "base.apk").write_bytes(b"base")
        (input_dir / "split.apk").write_bytes(b"split")
        output_dir = tmp_path / "output"

        keystores_used: list[Path] = []

        with patch("cli.commands.android.patch._ensure_tools"):
            with patch("cli.commands.android.patch._ensure_debug_keystore"):
                with patch("cli.commands.android.patch.patch_apk") as mock_patch:
                    with patch("cli.commands.android.patch.sign_apk") as mock_sign:

                        def capture_patch(apk: Path, out: Path, keystore: Path) -> Path:
                            keystores_used.append(keystore)
                            out.parent.mkdir(parents=True, exist_ok=True)
                            out.write_bytes(b"patched")
                            return out

                        def capture_sign(apk: Path, out: Path, ks: Path) -> Path:
                            keystores_used.append(ks)
                            out.write_bytes(b"signed")
                            return out

                        mock_patch.side_effect = capture_patch
                        mock_sign.side_effect = capture_sign

                        patch_apk_dir(input_dir, output_dir)

        # Both calls should use the same keystore
        assert len(keystores_used) == 2
        assert keystores_used[0] == keystores_used[1]
