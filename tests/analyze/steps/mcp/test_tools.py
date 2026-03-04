"""Tests for MCP investigation tools."""

from __future__ import annotations

import json

from cli.commands.analyze.steps.mcp.tools import (
    _execute_infer_request_schema,
    _execute_inspect_context,
    _execute_inspect_request,
    _execute_query_traces,
    make_mcp_tools,
)
from cli.commands.analyze.utils import sanitize_headers
from tests.conftest import make_context, make_trace


def _sample_traces():
    return [
        make_trace(
            "t_0001", "POST", "https://api.example.com/api/search", 200,
            timestamp=1000,
            request_body=json.dumps({"origin": "Paris", "destination": "Lyon", "currency": "EUR"}).encode(),
            response_body=b'{"results": []}',
        ),
        make_trace(
            "t_0002", "POST", "https://api.example.com/api/search", 200,
            timestamp=2000,
            request_body=json.dumps({"origin": "Lyon", "destination": "Marseille", "currency": "EUR"}).encode(),
            response_body=b'{"results": []}',
        ),
        make_trace(
            "t_0003", "GET", "https://api.example.com/api/users/123", 200,
            timestamp=3000,
            response_body=b'{"id": 123, "name": "Alice"}',
        ),
    ]


class TestInspectRequest:
    def test_returns_request_only(self) -> None:
        traces = _sample_traces()
        index = {t.meta.id: t for t in traces}
        result = _execute_inspect_request({"trace_id": "t_0001"}, index)
        parsed = json.loads(result)
        assert parsed["method"] == "POST"
        assert "search" in parsed["url"]
        assert "request_headers" in parsed
        # Must NOT include response body
        assert "response_body" not in parsed
        assert "response_headers" not in parsed

    def test_not_found(self) -> None:
        result = _execute_inspect_request({"trace_id": "t_9999"}, {})
        assert "not found" in result


class TestInferRequestSchema:
    def test_merges_bodies(self) -> None:
        traces = _sample_traces()
        index = {t.meta.id: t for t in traces}
        result = _execute_infer_request_schema(
            {"trace_ids": ["t_0001", "t_0002"]}, index
        )
        schema = json.loads(result)
        assert schema["type"] == "object"
        props = schema["properties"]
        # currency is always "EUR" → observed should reflect that
        assert "EUR" in props["currency"]["observed"]
        # origin varies
        assert len(props["origin"]["observed"]) == 2

    def test_no_bodies(self) -> None:
        traces = _sample_traces()
        index = {t.meta.id: t for t in traces}
        result = _execute_infer_request_schema(
            {"trace_ids": ["t_0003"]}, index
        )
        assert "No JSON request bodies" in result

    def test_unknown_trace(self) -> None:
        result = _execute_infer_request_schema(
            {"trace_ids": ["t_9999"]}, {}
        )
        assert "No JSON request bodies" in result


class TestQueryTraces:
    def test_filter_by_url(self) -> None:
        traces = _sample_traces()
        result = _execute_query_traces(
            {"expression": '[.[] | select(.url | test("search")) | .id]'},
            traces,
        )
        parsed = json.loads(result)
        assert parsed == [["t_0001", "t_0002"]]

    def test_filter_by_path(self) -> None:
        traces = _sample_traces()
        result = _execute_query_traces(
            {"expression": '[.[] | select(.path | test("/api/users/")) | .id]'},
            traces,
        )
        parsed = json.loads(result)
        assert parsed == [["t_0003"]]

    def test_extract_body_field(self) -> None:
        traces = _sample_traces()
        result = _execute_query_traces(
            {"expression": '[.[] | select(.request_body != null) | {id, origin: .request_body.origin}]'},
            traces,
        )
        parsed = json.loads(result)
        items = parsed[0]
        assert len(items) == 2
        assert items[0] == {"id": "t_0001", "origin": "Paris"}
        assert items[1] == {"id": "t_0002", "origin": "Lyon"}

    def test_filter_by_status(self) -> None:
        traces = _sample_traces() + [
            make_trace("t_0004", "GET", "https://api.example.com/api/fail", 404, timestamp=4000),
            make_trace("t_0005", "POST", "https://api.example.com/api/error", 500, timestamp=5000),
        ]
        result = _execute_query_traces(
            {"expression": '[.[] | select(.status >= 400)]'},
            traces,
        )
        parsed = json.loads(result)
        ids = [t["id"] for t in parsed[0]]
        assert ids == ["t_0004", "t_0005"]

    def test_invalid_expression(self) -> None:
        traces = _sample_traces()
        result = _execute_query_traces(
            {"expression": "[.[] | select(.invalid syntax"},
            traces,
        )
        assert "Invalid jq expression" in result

    def test_output_too_large(self) -> None:
        from cli.commands.analyze.steps.mcp.tools import _QUERY_TRACES_MAX_OUTPUT

        # Create traces with large response bodies that will exceed the limit
        traces = [
            make_trace(
                f"t_{i:04d}", "GET",
                f"https://api.example.com/api/items/{i}", 200,
                timestamp=i * 1000,
                response_body=json.dumps({"data": "x" * 500, "index": i}).encode(),
            )
            for i in range(_QUERY_TRACES_MAX_OUTPUT // 100)
        ]
        result = _execute_query_traces(
            {"expression": "[.[] | .response_body]"},
            traces,
        )
        assert "Output too large" in result
        assert "more selective query" in result


class TestInspectContext:
    def test_found_context(self) -> None:
        ctx = make_context(
            "c_0001", 1000, action="click", text="Search",
            page_url="https://example.com/home",
        )
        index = {ctx.meta.id: ctx}
        result = _execute_inspect_context({"context_id": "c_0001"}, index)
        parsed = json.loads(result)
        assert parsed["action"] == "click"
        assert parsed["element"]["text"] == "Search"
        assert parsed["element"]["tag"] == "BUTTON"
        assert parsed["page"]["url"] == "https://example.com/home"

    def test_not_found(self) -> None:
        result = _execute_inspect_context({"context_id": "c_9999"}, {})
        assert "not found" in result

    def test_page_content_included(self) -> None:
        from cli.commands.capture.types import Context
        from cli.formats.capture_bundle import (
            ContextMeta,
            ElementInfo,
            PageContent,
            PageInfo,
            ViewportInfo,
        )

        ctx = Context(
            meta=ContextMeta(
                id="c_0010",
                timestamp=5000,
                action="click",
                element=ElementInfo(selector="button", tag="BUTTON", text="Go"),
                page=PageInfo(
                    url="https://example.com",
                    title="Home",
                    content=PageContent(
                        headings=["Welcome", "Features"],
                        navigation=["Home", "About"],
                        main_text="Main content here",
                        forms=[],
                        tables=[],
                        alerts=["Sale today!"],
                    ),
                ),
                viewport=ViewportInfo(width=1440, height=900),
            )
        )
        index = {ctx.meta.id: ctx}
        result = _execute_inspect_context({"context_id": "c_0010"}, index)
        parsed = json.loads(result)
        assert "page_content" in parsed
        pc = parsed["page_content"]
        assert pc["headings"] == ["Welcome", "Features"]
        assert pc["navigation"] == ["Home", "About"]
        assert pc["main_text"] == "Main content here"
        assert pc["alerts"] == ["Sale today!"]


class TestMakeMcpTools:
    def test_tool_set_completeness(self) -> None:
        traces = _sample_traces()
        tools, executors = make_mcp_tools(traces)

        tool_names = {t["name"] for t in tools}
        assert "inspect_request" in tool_names
        assert "inspect_trace" in tool_names
        assert "infer_request_schema" in tool_names
        assert "query_traces" in tool_names
        assert "decode_base64" in tool_names
        assert "decode_url" in tool_names
        assert "decode_jwt" in tool_names
        # No inspect_context without contexts
        assert "inspect_context" not in tool_names

        assert set(tool_names) == set(executors.keys())

    def test_includes_inspect_context_with_contexts(self) -> None:
        traces = _sample_traces()
        contexts = [make_context("c_0001", 1000)]
        tools, executors = make_mcp_tools(traces, contexts=contexts)

        tool_names = {t["name"] for t in tools}
        assert "inspect_context" in tool_names
        assert set(tool_names) == set(executors.keys())


class TestSanitizeHeaders:
    def test_strips_noise_headers(self) -> None:
        headers = {
            ":authority": "api.example.com",
            ":method": "GET",
            ":path": "/api/data",
            ":scheme": "https",
            "sec-ch-ua": '"Chromium";v="133"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Linux"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "accept-encoding": "gzip, deflate, br",
            "user-agent": "Mozilla/5.0 ...",
            "priority": "u=1, i",
            "content-type": "application/json",
            "authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.long-token-value",
        }
        result = sanitize_headers(headers)
        # All noise headers should be gone
        for key in (":authority", ":method", ":path", ":scheme",
                    "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
                    "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site",
                    "accept-encoding", "priority"):
            assert key not in result
        # user-agent should be preserved (needed for WAF/API compatibility)
        assert "user-agent" in result
        assert result["user-agent"] == "Mozilla/5.0 ..."
        # Meaningful headers should remain
        assert "content-type" in result
        assert result["content-type"] == "application/json"
        # Auth headers should be redacted but present
        assert "authorization" in result
        assert "...[redacted]" in result["authorization"]

    def test_keeps_all_non_noise_headers(self) -> None:
        headers = {
            "content-type": "application/json",
            "x-custom": "value",
            "accept": "application/json",
        }
        result = sanitize_headers(headers)
        assert result == headers
