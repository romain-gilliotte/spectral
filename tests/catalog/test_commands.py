"""Tests for catalog CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
import pytest

from cli.formats.catalog import CatalogToken
from cli.formats.mcp_tool import ToolDefinition, ToolRequest
from cli.main import cli


def _make_tool(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Tool {name}",
        parameters={"type": "object", "properties": {}},
        request=ToolRequest(method="GET", url=f"https://api.example.com/api/{name}"),
    )


class TestCatalogLogin:
    @patch("cli.commands.catalog.login.webbrowser")
    @patch("cli.helpers.github.requests")
    def test_login_success(
        self,
        mock_requests: MagicMock,
        mock_webbrowser: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))

        # Mock device flow
        device_resp = MagicMock()
        device_resp.status_code = 200
        device_resp.json.return_value = {
            "device_code": "dc_123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "interval": 0,
        }
        device_resp.raise_for_status = MagicMock()

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"access_token": "ghu_test123"}
        token_resp.raise_for_status = MagicMock()

        user_resp = MagicMock()
        user_resp.status_code = 200
        user_resp.json.return_value = {"login": "testuser"}
        user_resp.raise_for_status = MagicMock()

        mock_requests.post.side_effect = [device_resp, token_resp]
        mock_requests.get.return_value = user_resp

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "login"])

        assert result.exit_code == 0, result.output
        assert "testuser" in result.output

        # Verify token was saved
        token_path = tmp_path / "catalog_token.json"
        assert token_path.is_file()
        saved = CatalogToken.model_validate_json(token_path.read_text())
        assert saved.username == "testuser"
        assert saved.access_token == "ghu_test123"

    def test_login_already_logged_in_decline(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))

        # Write existing token
        token_path = tmp_path / "catalog_token.json"
        token_path.write_text(
            CatalogToken(access_token="old", username="existing").model_dump_json()
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "login"], input="n\n")

        assert result.exit_code == 0
        assert "existing" in result.output


class TestCatalogLogout:
    def test_logout_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        token_path = tmp_path / "catalog_token.json"
        token_path.write_text(
            CatalogToken(access_token="tok", username="user").model_dump_json()
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "logout"])

        assert result.exit_code == 0
        assert "Logged out" in result.output
        assert not token_path.exists()

    def test_logout_not_logged_in(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        runner = CliRunner()
        result = runner.invoke(cli, ["community", "logout"])

        assert result.exit_code == 0
        assert "Not logged in" in result.output


class TestCatalogPublish:
    def test_publish_not_logged_in(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import ensure_app, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp", "My App")
        write_tools("myapp", [_make_tool("t1")])

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "publish", "myapp"])

        assert result.exit_code != 0
        assert "Not logged in" in result.output

    def test_publish_no_tools(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import ensure_app

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp")

        # Write token
        token_path = tmp_path / "catalog_token.json"
        token_path.write_text(
            CatalogToken(access_token="tok", username="user").model_dump_json()
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "publish", "myapp"])

        assert result.exit_code != 0
        assert "no tools" in result.output

    def test_publish_double_underscore_rejected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cli.helpers.storage import ensure_app, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("user__app")
        write_tools("user__app", [_make_tool("t1")])

        token_path = tmp_path / "catalog_token.json"
        token_path.write_text(
            CatalogToken(access_token="tok", username="user").model_dump_json()
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "publish", "user__app"])

        assert result.exit_code != 0
        assert "Cannot publish" in result.output

    @patch("cli.helpers.catalog_api.requests")
    def test_publish_success(
        self,
        mock_requests: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from cli.helpers.storage import ensure_app, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp", "My App")
        write_tools("myapp", [_make_tool("t1")])

        token_path = tmp_path / "catalog_token.json"
        token_path.write_text(
            CatalogToken(access_token="tok", username="user").model_dump_json()
        )

        resp_mock = MagicMock()
        resp_mock.ok = True
        resp_mock.status_code = 200
        resp_mock.json.return_value = {
            "pr_url": "https://github.com/org/spectral-tools/pull/1",
            "branch": "submissions/user/myapp",
            "pr_created": True,
        }
        mock_requests.post.return_value = resp_mock

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "publish", "myapp"])

        assert result.exit_code == 0, result.output
        assert "Pull request created successfully" in result.output

        # No auth script → payload should not include auth_script
        payload = mock_requests.post.call_args.kwargs["json"]
        assert "auth_script" not in payload

    @patch("cli.helpers.catalog_api.requests")
    def test_publish_includes_auth_script(
        self,
        mock_requests: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from cli.helpers.storage import auth_script_path, ensure_app, write_tools

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        ensure_app("myapp", "My App")
        write_tools("myapp", [_make_tool("t1")])

        # Write an auth script
        script_content = "def acquire_token():\n    pass\n"
        auth_script_path("myapp").write_text(script_content)

        token_path = tmp_path / "catalog_token.json"
        token_path.write_text(
            CatalogToken(access_token="tok", username="user").model_dump_json()
        )

        resp_mock = MagicMock()
        resp_mock.ok = True
        resp_mock.status_code = 200
        resp_mock.json.return_value = {
            "pr_url": "https://github.com/org/spectral-tools/pull/1",
            "branch": "submissions/user/myapp",
            "pr_created": True,
        }
        mock_requests.post.return_value = resp_mock

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "publish", "myapp"])

        assert result.exit_code == 0, result.output
        assert "with auth script" in result.output

        payload = mock_requests.post.call_args.kwargs["json"]
        assert payload["auth_script"] == script_content

    def test_publish_nonexistent_app(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        runner = CliRunner()
        result = runner.invoke(cli, ["community", "publish", "nope"])

        assert result.exit_code != 0
        assert "not found" in result.output


class TestCatalogSearch:
    @patch("cli.helpers.catalog_api.requests")
    def test_search_results(
        self,
        mock_requests: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))

        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.ok = True
        search_resp.raise_for_status = MagicMock()
        search_resp.json.return_value = [
            {
                "username": "romain",
                "app_name": "planity-com",
                "display_name": "Planity",
                "description": "Book appointments",
                "base_urls": ["https://planity.com"],
                "tool_count": 5,
                "published_at": "2026-03-12T10:00:00Z",
                "stats": {"total_calls": 100, "success_rate": 0.95, "unique_users": 10},
            }
        ]

        # The stats POST is best-effort (may or may not be called)
        stats_resp = MagicMock()
        stats_resp.status_code = 204
        mock_requests.post.return_value = stats_resp
        mock_requests.get.return_value = search_resp

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "search", "planity"])

        assert result.exit_code == 0, result.output
        assert "planity" in result.output.lower()

    @patch("cli.helpers.catalog_api.requests")
    def test_search_shows_installed_badge(
        self,
        mock_requests: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from cli.helpers.storage import ensure_app

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        # Pre-install one app locally
        ensure_app("romain__planity-com")

        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.raise_for_status = MagicMock()
        search_resp.json.return_value = [
            {
                "username": "romain",
                "app_name": "planity-com",
                "display_name": "Planity",
                "description": "Book appointments",
                "base_urls": ["https://planity.com"],
                "tool_count": 5,
                "published_at": "2026-03-12T10:00:00Z",
                "stats": {"total_calls": 0, "success_rate": 0, "unique_users": 0},
            }
        ]
        mock_requests.post.return_value = MagicMock(status_code=204)
        mock_requests.get.return_value = search_resp

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "search", "planity"])

        assert result.exit_code == 0, result.output
        assert "Installed" in result.output

    @patch("cli.helpers.catalog_api.requests")
    def test_search_no_results(
        self,
        mock_requests: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))

        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.raise_for_status = MagicMock()
        search_resp.json.return_value = []
        mock_requests.get.return_value = search_resp
        mock_requests.post.return_value = MagicMock(status_code=204)

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "search", "nonexistent"])

        assert result.exit_code == 0
        assert "No results" in result.output


class TestSendStatsBestEffort:
    @pytest.mark.skip(reason="Stats reporting disabled until batched approach is implemented")
    @patch("cli.helpers.catalog_api.requests")
    def test_sends_stats_for_catalog_apps(
        self,
        mock_requests: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from cli.helpers.storage import ensure_app, record_tool_call

        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))

        # Create a catalog-installed app with stats
        ensure_app("romain__planity-com")
        record_tool_call("romain__planity-com", "search", 200, 100.0)
        record_tool_call("romain__planity-com", "search", 200, 200.0)

        # Create a local (non-catalog) app — its stats should NOT be sent
        ensure_app("myapp")
        record_tool_call("myapp", "fetch", 200, 50.0)

        search_resp = MagicMock()
        search_resp.raise_for_status = MagicMock()
        search_resp.json.return_value = []
        mock_requests.get.return_value = search_resp

        stats_resp = MagicMock()
        stats_resp.status_code = 204
        mock_requests.post.return_value = stats_resp

        runner = CliRunner()
        runner.invoke(cli, ["community", "search", "anything"])

        # Check that stats POST was called with catalog app stats
        post_calls = mock_requests.post.call_args_list
        assert len(post_calls) == 1
        payload = post_calls[0].kwargs["json"]
        assert payload["user_hash"]  # non-empty hash
        assert len(payload["stats"]) == 1  # only catalog app
        assert payload["stats"][0]["collection_ref"] == "romain/planity-com"
        assert payload["stats"][0]["tool_name"] == "search"
        assert payload["stats"][0]["call_count"] == 2
        assert payload["stats"][0]["success_count"] == 2


class TestCatalogInstall:
    def test_install_invalid_ref(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        runner = CliRunner()
        result = runner.invoke(cli, ["community", "install", "badref"])

        assert result.exit_code != 0
        assert "Invalid collection reference" in result.output

    @patch("cli.helpers.github.requests")
    def test_install_success(
        self,
        mock_requests: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))

        tool = _make_tool("search")
        manifest: dict[str, Any] = {
            "display_name": "Test App",
            "description": "Test tools",
            "base_urls": ["https://example.com"],
            "tool_count": 1,
            "published_at": "2026-03-12T10:00:00Z",
            "spectral_version": "0.3.1",
        }

        # Mock contents API response
        contents_resp = MagicMock()
        contents_resp.status_code = 200
        contents_resp.raise_for_status = MagicMock()
        contents_resp.json.return_value = [
            {
                "name": "manifest.json",
                "type": "file",
                "download_url": "https://raw.githubusercontent.com/manifest.json",
            },
            {
                "name": "search.json",
                "type": "file",
                "download_url": "https://raw.githubusercontent.com/search.json",
            },
        ]

        manifest_resp = MagicMock()
        manifest_resp.status_code = 200
        manifest_resp.raise_for_status = MagicMock()
        manifest_resp.text = json.dumps(manifest)

        tool_resp = MagicMock()
        tool_resp.status_code = 200
        tool_resp.raise_for_status = MagicMock()
        tool_resp.text = tool.model_dump_json()

        mock_requests.get.side_effect = [contents_resp, manifest_resp, tool_resp]

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "install", "romain/test-app"])

        assert result.exit_code == 0, result.output
        assert "Installed 1 tools" in result.output
        assert "romain__test-app" in result.output

        # Verify tools were written
        from cli.helpers.storage import auth_script_path, list_tools, load_app_meta

        tools = list_tools("romain__test-app")
        assert len(tools) == 1
        assert tools[0].name == "search"

        # Verify catalog_source was set on AppMeta
        meta = load_app_meta("romain__test-app")
        assert meta.catalog_source is not None
        assert meta.catalog_source.username == "romain"
        assert meta.catalog_source.app_name == "test-app"
        assert meta.display_name == "Test App"

        # No auth script in this install
        assert not auth_script_path("romain__test-app").is_file()

    @patch("cli.helpers.github.requests")
    def test_install_with_auth_script(
        self,
        mock_requests: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))

        tool = _make_tool("search")
        manifest: dict[str, Any] = {
            "display_name": "Test App",
            "description": "Test tools",
            "base_urls": ["https://example.com"],
            "tool_count": 1,
            "published_at": "2026-03-12T10:00:00Z",
            "spectral_version": "0.3.1",
        }
        auth_code = "def acquire_token():\n    pass\n"

        contents_resp = MagicMock()
        contents_resp.status_code = 200
        contents_resp.raise_for_status = MagicMock()
        contents_resp.json.return_value = [
            {
                "name": "manifest.json",
                "type": "file",
                "download_url": "https://raw.githubusercontent.com/manifest.json",
            },
            {
                "name": "search.json",
                "type": "file",
                "download_url": "https://raw.githubusercontent.com/search.json",
            },
            {
                "name": "auth_acquire.py",
                "type": "file",
                "download_url": "https://raw.githubusercontent.com/auth_acquire.py",
            },
        ]

        manifest_resp = MagicMock()
        manifest_resp.status_code = 200
        manifest_resp.raise_for_status = MagicMock()
        manifest_resp.text = json.dumps(manifest)

        tool_resp = MagicMock()
        tool_resp.status_code = 200
        tool_resp.raise_for_status = MagicMock()
        tool_resp.text = tool.model_dump_json()

        auth_resp = MagicMock()
        auth_resp.status_code = 200
        auth_resp.raise_for_status = MagicMock()
        auth_resp.text = auth_code

        mock_requests.get.side_effect = [contents_resp, manifest_resp, tool_resp, auth_resp]

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "install", "romain/test-app"])

        assert result.exit_code == 0, result.output
        assert "Installed 1 tools" in result.output
        assert "spectral auth login" in result.output

        from cli.helpers.storage import auth_script_path

        script_path = auth_script_path("romain__test-app")
        assert script_path.is_file()
        assert script_path.read_text() == auth_code

    @patch("cli.helpers.github.requests")
    def test_install_no_files(
        self,
        mock_requests: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))

        contents_resp = MagicMock()
        contents_resp.status_code = 200
        contents_resp.raise_for_status = MagicMock()
        contents_resp.json.return_value = []
        mock_requests.get.return_value = contents_resp

        runner = CliRunner()
        result = runner.invoke(cli, ["community", "install", "user/app"])

        assert result.exit_code != 0
        assert "No files found" in result.output
