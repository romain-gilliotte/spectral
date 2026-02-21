"""Tests for UnsupportedBranch."""

import asyncio
import json

import pytest

from cli.commands.analyze.steps.other.skip import UnsupportedBranch
from cli.commands.analyze.steps.types import AuthInfo, BranchContext
from cli.formats.capture_bundle import Header
from tests.conftest import make_trace


def _make_ctx(messages: list[str]) -> BranchContext:
    """Create a minimal BranchContext for testing."""

    async def _noop_auth() -> AuthInfo:
        return AuthInfo()

    loop = asyncio.get_event_loop()
    auth_task = loop.create_task(_noop_auth())
    return BranchContext(
        base_url="https://example.com",
        app_name="Test",
        source_filename="test.zip",
        correlations=[],
        all_filtered_traces=[],
        skip_enrich=True,
        on_progress=messages.append,
        auth_task=auth_task,
    )


class TestUnsupportedBranch:
    @pytest.mark.asyncio
    async def test_empty_input_no_progress(self):
        messages: list[str] = []
        branch = UnsupportedBranch()
        result = await branch.run([], _make_ctx(messages))
        assert result is None
        assert messages == []

    @pytest.mark.asyncio
    async def test_single_protocol_summary(self):
        messages: list[str] = []
        traces = [
            make_trace(
                "t_1", "GET", "https://example.com/a", 200, 1000,
                request_headers=[Header(name="X-RestLi-Protocol-Version", value="2.0.0")],
            ),
            make_trace(
                "t_2", "GET", "https://example.com/b", 200, 1001,
                request_headers=[Header(name="X-RestLi-Protocol-Version", value="2.0.0")],
            ),
        ]
        branch = UnsupportedBranch()
        result = await branch.run(traces, _make_ctx(messages))
        assert result is None
        assert len(messages) == 1
        assert "2 Rest.li" in messages[0]
        assert "unsupported protocols" in messages[0]

    @pytest.mark.asyncio
    async def test_multiple_protocols_summary(self):
        messages: list[str] = []
        traces = [
            make_trace(
                "t_1", "GET", "https://example.com/a", 200, 1000,
                response_headers=[Header(name="Content-Type", value="text/event-stream")],
            ),
            make_trace(
                "t_2", "POST", "https://example.com/b", 200, 1001,
                request_body=json.dumps({"jsonrpc": "2.0", "method": "ping", "id": 1}).encode(),
                request_headers=[Header(name="Content-Type", value="application/json")],
            ),
            make_trace(
                "t_3", "GET", "https://example.com/c", 200, 1002,
                response_headers=[Header(name="Content-Type", value="text/event-stream")],
            ),
            make_trace(
                "t_4", "GET", "https://example.com/d", 200, 1003,
                response_headers=[Header(name="Content-Type", value="text/event-stream")],
            ),
        ]
        branch = UnsupportedBranch()
        result = await branch.run(traces, _make_ctx(messages))
        assert result is None
        assert len(messages) == 1
        # Most common first
        assert "3 Server-Sent Events" in messages[0]
        assert "1 JSON-RPC" in messages[0]

    @pytest.mark.asyncio
    async def test_returns_none(self):
        """Branch always returns None (no output artifact)."""
        messages: list[str] = []
        traces = [
            make_trace(
                "t_1", "POST", "https://example.com/ws", 200, 1000,
                request_headers=[Header(name="Content-Type", value="application/soap+xml")],
            ),
        ]
        branch = UnsupportedBranch()
        result = await branch.run(traces, _make_ctx(messages))
        assert result is None
