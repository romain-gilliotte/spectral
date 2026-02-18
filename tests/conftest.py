"""Shared test fixtures for spectral tests."""

from __future__ import annotations

import json

import pytest

from cli.commands.capture.types import CaptureBundle, Context, Trace, WsConnection, WsMessage
from cli.formats.capture_bundle import (
    AppInfo,
    BrowserInfo,
    CaptureManifest,
    CaptureStats,
    ContextMeta,
    ElementInfo,
    Header,
    PageInfo,
    RequestMeta,
    ResponseMeta,
    Timeline,
    TimelineEvent,
    TimingInfo,
    TraceMeta,
    ViewportInfo,
    WsConnectionMeta,
    WsMessageMeta,
)


@pytest.fixture
def sample_manifest() -> CaptureManifest:
    return CaptureManifest(
        capture_id="test-capture-001",
        created_at="2026-02-13T15:30:00Z",
        app=AppInfo(
            name="Test App",
            base_url="https://example.com",
            title="Test Application",
        ),
        browser=BrowserInfo(name="Chrome", version="133.0"),
        duration_ms=5000,
        stats=CaptureStats(
            trace_count=3, ws_connection_count=1, ws_message_count=2, context_count=2
        ),
    )


def make_trace(
    trace_id: str,
    method: str,
    url: str,
    status: int,
    timestamp: int,
    request_body: bytes = b"",
    response_body: bytes = b"",
    request_headers: list[Header] | None = None,
    response_headers: list[Header] | None = None,
    context_refs: list[str] | None = None,
) -> Trace:
    """Helper to create a Trace with minimal boilerplate."""
    req_body_file = f"{trace_id}_request.bin" if request_body else None
    resp_body_file = f"{trace_id}_response.bin" if response_body else None

    return Trace(
        meta=TraceMeta(
            id=trace_id,
            timestamp=timestamp,
            request=RequestMeta(
                method=method,
                url=url,
                headers=request_headers or [],
                body_file=req_body_file,
                body_size=len(request_body),
            ),
            response=ResponseMeta(
                status=status,
                status_text="OK" if status == 200 else "Error",
                headers=response_headers
                or [
                    Header(name="Content-Type", value="application/json"),
                ],
                body_file=resp_body_file,
                body_size=len(response_body),
            ),
            timing=TimingInfo(total_ms=100),
            context_refs=context_refs or [],
        ),
        request_body=request_body,
        response_body=response_body,
    )


def make_context(
    context_id: str,
    timestamp: int,
    action: str = "click",
    selector: str = "button#submit",
    text: str = "Submit",
    page_url: str = "https://example.com/page",
) -> Context:
    """Helper to create a Context with minimal boilerplate."""
    return Context(
        meta=ContextMeta(
            id=context_id,
            timestamp=timestamp,
            action=action,
            element=ElementInfo(selector=selector, tag="BUTTON", text=text),
            page=PageInfo(url=page_url, title="Test Page"),
            viewport=ViewportInfo(width=1440, height=900),
        )
    )


def make_ws_connection(
    ws_id: str,
    url: str,
    timestamp: int,
    protocols: list[str] | None = None,
    messages: list[WsMessage] | None = None,
) -> WsConnection:
    """Helper to create a WsConnection."""
    return WsConnection(
        meta=WsConnectionMeta(
            id=ws_id,
            timestamp=timestamp,
            url=url,
            protocols=protocols or [],
            message_count=len(messages) if messages else 0,
        ),
        messages=messages or [],
    )


def make_ws_message(
    msg_id: str,
    conn_ref: str,
    timestamp: int,
    direction: str = "send",
    payload: bytes = b"",
) -> WsMessage:
    """Helper to create a WsMessage."""
    return WsMessage(
        meta=WsMessageMeta(
            id=msg_id,
            connection_ref=conn_ref,
            timestamp=timestamp,
            direction=direction,
            opcode="text" if payload else "text",
            payload_file=f"{msg_id}.bin" if payload else None,
            payload_size=len(payload),
        ),
        payload=payload,
    )


@pytest.fixture
def sample_traces() -> list[Trace]:
    """Create sample traces for testing."""
    return [
        make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/api/users",
            200,
            timestamp=1000000,
            response_body=json.dumps(
                [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
            ).encode(),
            request_headers=[Header(name="Authorization", value="Bearer token123")],
        ),
        make_trace(
            "t_0002",
            "GET",
            "https://api.example.com/api/users/123/orders",
            200,
            timestamp=1001000,
            response_body=json.dumps(
                {"orders": [{"id": "o1", "total": 42.5}]}
            ).encode(),
            request_headers=[Header(name="Authorization", value="Bearer token123")],
        ),
        make_trace(
            "t_0003",
            "GET",
            "https://api.example.com/api/users/456/orders",
            200,
            timestamp=1002000,
            response_body=json.dumps(
                {"orders": [{"id": "o2", "total": 99.0}]}
            ).encode(),
            request_headers=[Header(name="Authorization", value="Bearer token123")],
        ),
        make_trace(
            "t_0004",
            "POST",
            "https://api.example.com/api/orders",
            201,
            timestamp=1003000,
            request_body=json.dumps({"product_id": "p1", "quantity": 2}).encode(),
            response_body=json.dumps({"id": "o3", "status": "created"}).encode(),
            request_headers=[
                Header(name="Authorization", value="Bearer token123"),
                Header(name="Content-Type", value="application/json"),
            ],
        ),
    ]


@pytest.fixture
def sample_contexts() -> list[Context]:
    """Create sample contexts for testing."""
    return [
        make_context(
            "c_0001",
            timestamp=999000,
            action="click",
            selector="nav#users",
            text="Users",
            page_url="https://example.com/home",
        ),
        make_context(
            "c_0002",
            timestamp=1002500,
            action="click",
            selector="button#create-order",
            text="Create Order",
            page_url="https://example.com/orders",
        ),
    ]


@pytest.fixture
def sample_bundle(
    sample_manifest: CaptureManifest,
    sample_traces: list[Trace],
    sample_contexts: list[Context],
) -> CaptureBundle:
    """Create a complete sample capture bundle."""
    ws_msg1 = make_ws_message(
        "ws_0001_m001", "ws_0001", 1001500, "send", b'{"type":"subscribe","id":"1"}'
    )
    ws_msg2 = make_ws_message(
        "ws_0001_m002",
        "ws_0001",
        1001600,
        "receive",
        b'{"type":"next","id":"1","payload":{"data":123}}',
    )

    ws_conn = make_ws_connection(
        "ws_0001",
        "wss://realtime.example.com/ws",
        1001000,
        protocols=["graphql-ws"],
        messages=[ws_msg1, ws_msg2],
    )

    timeline = Timeline(
        events=[
            TimelineEvent(timestamp=999000, type="context", ref="c_0001"),
            TimelineEvent(timestamp=1000000, type="trace", ref="t_0001"),
            TimelineEvent(timestamp=1001000, type="trace", ref="t_0002"),
            TimelineEvent(timestamp=1001000, type="ws_open", ref="ws_0001"),
            TimelineEvent(timestamp=1001500, type="ws_message", ref="ws_0001_m001"),
            TimelineEvent(timestamp=1001600, type="ws_message", ref="ws_0001_m002"),
            TimelineEvent(timestamp=1002000, type="trace", ref="t_0003"),
            TimelineEvent(timestamp=1002500, type="context", ref="c_0002"),
            TimelineEvent(timestamp=1003000, type="trace", ref="t_0004"),
        ]
    )

    return CaptureBundle(
        manifest=sample_manifest,
        traces=sample_traces,
        ws_connections=[ws_conn],
        contexts=sample_contexts,
        timeline=timeline,
    )
