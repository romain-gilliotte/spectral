"""Tests for MCP tool format (mcp_tool.py)."""

from __future__ import annotations

import pytest

from cli.formats.mcp_tool import ToolRequest


class TestToolRequestHeaderValidation:
    def test_rejects_param_ref_in_headers(self) -> None:
        """ToolRequest.headers is dict[str, str] — $param dicts must be rejected."""
        with pytest.raises(Exception):
            ToolRequest.model_validate({
                "method": "GET",
                "url": "https://api.example.com/api/cars",
                "headers": {"x-authorization": {"$param": "auth_token"}},
            })

    def test_accepts_literal_headers(self) -> None:
        req = ToolRequest.model_validate({
            "method": "GET",
            "url": "https://api.example.com/api/cars",
            "headers": {"Accept": "application/json"},
        })
        assert req.headers == {"Accept": "application/json"}
