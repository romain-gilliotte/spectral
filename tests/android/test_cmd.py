"""Tests for the Android CLI commands."""

from click.testing import CliRunner

from cli.main import cli


class TestAndroidCLI:
    def test_android_group_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["android", "--help"])
        assert result.exit_code == 0
        assert "pull" in result.output
        assert "patch" in result.output
        assert "install" in result.output
        assert "cert" in result.output

    def test_pull_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["android", "pull", "--help"])
        assert result.exit_code == 0
        assert "PACKAGE" in result.output

    def test_patch_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["android", "patch", "--help"])
        assert result.exit_code == 0
        assert "APK_PATH" in result.output

    def test_install_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["android", "install", "--help"])
        assert result.exit_code == 0
        assert "APK_PATH" in result.output

    def test_cert_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["android", "cert", "--help"])
        assert result.exit_code == 0
        assert "CERT_PATH" in result.output
