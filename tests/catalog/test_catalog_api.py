"""Tests for the catalog API client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cli.helpers.catalog_api import CatalogAPIError, publish, report_stats, search


class TestPublish:
    @patch("cli.helpers.catalog_api.requests")
    def test_success(self, mock_requests: MagicMock) -> None:
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json.return_value = {
            "pr_url": "https://github.com/org/spectral-tools/pull/42",
            "branch": "submissions/romain/planity-com",
        }
        mock_requests.post.return_value = resp

        result = publish(
            github_token="ghu_abc",
            app_name="planity-com",
            manifest={"display_name": "Planity"},
            tools=[{"name": "search"}],
        )
        assert result["pr_url"] == "https://github.com/org/spectral-tools/pull/42"

        # Verify the request payload
        call_args = mock_requests.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["github_token"] == "ghu_abc"
        assert payload["app_name"] == "planity-com"
        assert len(payload["tools"]) == 1

    @patch("cli.helpers.catalog_api.requests")
    def test_conflict_409(self, mock_requests: MagicMock) -> None:
        resp = MagicMock()
        resp.ok = False
        resp.status_code = 409
        resp.json.return_value = {"message": "PR already exists"}
        mock_requests.post.return_value = resp

        with pytest.raises(CatalogAPIError) as exc_info:
            publish("token", "app", {}, [])
        assert exc_info.value.status_code == 409
        assert "already exists" in exc_info.value.message

    @patch("cli.helpers.catalog_api.requests")
    def test_unauthorized_401(self, mock_requests: MagicMock) -> None:
        resp = MagicMock()
        resp.ok = False
        resp.status_code = 401
        resp.json.return_value = {"message": "Invalid token"}
        mock_requests.post.return_value = resp

        with pytest.raises(CatalogAPIError) as exc_info:
            publish("bad_token", "app", {}, [])
        assert exc_info.value.status_code == 401

    @patch("cli.helpers.catalog_api.requests")
    def test_validation_error_422(self, mock_requests: MagicMock) -> None:
        resp = MagicMock()
        resp.ok = False
        resp.status_code = 422
        resp.json.return_value = {"message": "Invalid tool schema"}
        mock_requests.post.return_value = resp

        with pytest.raises(CatalogAPIError) as exc_info:
            publish("token", "app", {}, [{"bad": "tool"}])
        assert exc_info.value.status_code == 422

    @patch("cli.helpers.catalog_api.requests")
    def test_server_error_non_json(self, mock_requests: MagicMock) -> None:
        resp = MagicMock()
        resp.ok = False
        resp.status_code = 500
        resp.text = "Internal Server Error"
        resp.json.side_effect = ValueError("not json")
        mock_requests.post.return_value = resp

        with pytest.raises(CatalogAPIError) as exc_info:
            publish("token", "app", {}, [])
        assert exc_info.value.status_code == 500
        assert "Internal Server Error" in exc_info.value.message


class TestSearch:
    @patch("cli.helpers.catalog_api.requests")
    def test_success(self, mock_requests: MagicMock) -> None:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = [
            {
                "username": "romain",
                "app_name": "planity-com",
                "display_name": "Planity",
                "description": "Book appointments",
                "tool_count": 5,
                "stats": {"total_calls": 100, "success_rate": 0.95},
            }
        ]
        mock_requests.get.return_value = resp

        results = search("planity")
        assert len(results) == 1
        assert results[0]["username"] == "romain"

        # Verify query parameter
        call_args = mock_requests.get.call_args
        assert call_args.kwargs["params"]["q"] == "planity"

    @patch("cli.helpers.catalog_api.requests")
    def test_empty_results(self, mock_requests: MagicMock) -> None:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = []
        mock_requests.get.return_value = resp

        results = search("nonexistent")
        assert results == []


class TestReportStats:
    @patch("cli.helpers.catalog_api.requests")
    def test_success(self, mock_requests: MagicMock) -> None:
        resp = MagicMock()
        resp.status_code = 204
        mock_requests.post.return_value = resp

        # Should not raise
        report_stats("hash123", [{"collection_ref": "u/a", "tool_name": "t", "call_count": 1}])

        call_args = mock_requests.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["user_hash"] == "hash123"
        assert len(payload["stats"]) == 1

    @patch("cli.helpers.catalog_api.requests")
    def test_failure_is_silent(self, mock_requests: MagicMock) -> None:
        """report_stats is best-effort — exceptions are swallowed."""
        mock_requests.post.side_effect = ConnectionError("offline")

        # Should not raise
        report_stats("hash", [{"collection_ref": "u/a"}])
