"""Tests for the GitHub helper (Device Flow + Contents API)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cli.helpers.github import (
    DeviceFlowError,
    DeviceFlowPending,
    download_directory,
    get_github_user,
    poll_for_token,
    start_device_flow,
)


class TestStartDeviceFlow:
    @patch("cli.helpers.github.requests")
    def test_success(self, mock_requests: MagicMock) -> None:
        resp = MagicMock()
        resp.json.return_value = {
            "device_code": "dc_abc",
            "user_code": "WXYZ-1234",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
        }
        resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = resp

        pending = start_device_flow()
        assert pending.device_code == "dc_abc"
        assert pending.user_code == "WXYZ-1234"
        assert pending.verification_uri == "https://github.com/login/device"
        assert pending.interval == 5

    @patch("cli.helpers.github.requests")
    def test_default_interval(self, mock_requests: MagicMock) -> None:
        resp = MagicMock()
        resp.json.return_value = {
            "device_code": "dc_abc",
            "user_code": "WXYZ-1234",
            "verification_uri": "https://github.com/login/device",
        }
        resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = resp

        pending = start_device_flow()
        assert pending.interval == 5  # default


class TestPollForToken:
    @patch("cli.helpers.github.time")
    @patch("cli.helpers.github.requests")
    def test_immediate_success(
        self, mock_requests: MagicMock, mock_time: MagicMock
    ) -> None:
        resp = MagicMock()
        resp.json.return_value = {"access_token": "ghu_success"}
        resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = resp

        pending = DeviceFlowPending("dc", "UC", "https://github.com/login/device", 0)
        token = poll_for_token(pending)
        assert token == "ghu_success"

    @patch("cli.helpers.github.time")
    @patch("cli.helpers.github.requests")
    def test_pending_then_success(
        self, mock_requests: MagicMock, mock_time: MagicMock
    ) -> None:
        pending_resp = MagicMock()
        pending_resp.json.return_value = {"error": "authorization_pending"}
        pending_resp.raise_for_status = MagicMock()

        success_resp = MagicMock()
        success_resp.json.return_value = {"access_token": "ghu_delayed"}
        success_resp.raise_for_status = MagicMock()

        mock_requests.post.side_effect = [pending_resp, success_resp]

        pending = DeviceFlowPending("dc", "UC", "https://github.com/login/device", 0)
        token = poll_for_token(pending)
        assert token == "ghu_delayed"

    @patch("cli.helpers.github.time")
    @patch("cli.helpers.github.requests")
    def test_slow_down_increases_interval(
        self, mock_requests: MagicMock, mock_time: MagicMock
    ) -> None:
        slow_resp = MagicMock()
        slow_resp.json.return_value = {"error": "slow_down"}
        slow_resp.raise_for_status = MagicMock()

        success_resp = MagicMock()
        success_resp.json.return_value = {"access_token": "ghu_slow"}
        success_resp.raise_for_status = MagicMock()

        mock_requests.post.side_effect = [slow_resp, success_resp]

        pending = DeviceFlowPending("dc", "UC", "https://github.com/login/device", 5)
        poll_for_token(pending)
        assert pending.interval == 10  # increased by 5

    @patch("cli.helpers.github.time")
    @patch("cli.helpers.github.requests")
    def test_expired_token(
        self, mock_requests: MagicMock, mock_time: MagicMock
    ) -> None:
        resp = MagicMock()
        resp.json.return_value = {"error": "expired_token"}
        resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = resp

        pending = DeviceFlowPending("dc", "UC", "https://github.com/login/device", 0)
        with pytest.raises(DeviceFlowError, match="expired"):
            poll_for_token(pending)

    @patch("cli.helpers.github.time")
    @patch("cli.helpers.github.requests")
    def test_access_denied(
        self, mock_requests: MagicMock, mock_time: MagicMock
    ) -> None:
        resp = MagicMock()
        resp.json.return_value = {"error": "access_denied"}
        resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = resp

        pending = DeviceFlowPending("dc", "UC", "https://github.com/login/device", 0)
        with pytest.raises(DeviceFlowError, match="denied"):
            poll_for_token(pending)


class TestGetGitHubUser:
    @patch("cli.helpers.github.requests")
    def test_success(self, mock_requests: MagicMock) -> None:
        resp = MagicMock()
        resp.json.return_value = {
            "login": "testuser",
            "name": "Test User",
            "email": "test@example.com",
        }
        resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = resp

        user = get_github_user("ghu_token")
        assert user["login"] == "testuser"
        assert user["name"] == "Test User"

        # Verify correct auth header was sent
        call_args = mock_requests.get.call_args
        assert "Bearer ghu_token" in call_args.kwargs["headers"]["Authorization"]


class TestDownloadDirectory:
    @patch("cli.helpers.github.requests")
    def test_success(self, mock_requests: MagicMock) -> None:
        contents_resp = MagicMock()
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
                "name": "subdir",
                "type": "dir",
            },
            {
                "name": "README.md",
                "type": "file",
                "download_url": "https://raw.githubusercontent.com/README.md",
            },
        ]
        contents_resp.raise_for_status = MagicMock()

        manifest_resp = MagicMock()
        manifest_resp.text = '{"display_name": "Test"}'
        manifest_resp.raise_for_status = MagicMock()

        search_resp = MagicMock()
        search_resp.text = '{"name": "search"}'
        search_resp.raise_for_status = MagicMock()

        mock_requests.get.side_effect = [contents_resp, manifest_resp, search_resp]

        files = download_directory("romain", "planity-com")

        assert len(files) == 2  # only .json files, not dirs or .md
        assert files[0]["name"] == "manifest.json"
        assert files[1]["name"] == "search.json"

    @patch("cli.helpers.github.requests")
    def test_custom_repo(self, mock_requests: MagicMock) -> None:
        contents_resp = MagicMock()
        contents_resp.json.return_value = []
        contents_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = contents_resp

        download_directory("user", "app", repo="org/custom-repo")

        url_arg = mock_requests.get.call_args[0][0]
        assert "org/custom-repo" in url_arg

    @patch("cli.helpers.github.requests")
    def test_empty_directory(self, mock_requests: MagicMock) -> None:
        contents_resp = MagicMock()
        contents_resp.json.return_value = []
        contents_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = contents_resp

        files = download_directory("user", "app")
        assert files == []
