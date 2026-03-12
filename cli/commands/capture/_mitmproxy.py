"""Shared mitmproxy infrastructure: conversions, launch helpers."""

from __future__ import annotations

import asyncio
import re
import signal
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import FrameType

    from mitmproxy.http import Headers as mitmproxy_Headers, HTTPFlow

from cli.commands.capture.types import Trace, WsConnection, WsMessage
from cli.formats.capture_bundle import (
    Header,
    Initiator,
    RequestMeta,
    ResponseMeta,
    TimingInfo,
    TraceMeta,
    WsConnectionMeta,
)


def _header_items(headers: mitmproxy_Headers) -> list[tuple[str, str]]:
    """Extract header items from mitmproxy Headers, typed for pyright."""
    items: list[tuple[str, str]] = list(headers.items(multi=True))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    return items


def flow_to_trace(flow: HTTPFlow, trace_id: str) -> Trace:
    """Convert a mitmproxy HTTPFlow to a Trace."""
    req = flow.request
    resp = flow.response

    req_headers = [Header(name=k, value=v) for k, v in _header_items(req.headers)]
    req_body = req.content or b""

    resp_headers: list[Header] = []
    resp_body = b""
    status = 0
    status_text = ""
    if resp:
        resp_headers = [Header(name=k, value=v) for k, v in _header_items(resp.headers)]
        resp_body = resp.content or b""
        status = resp.status_code
        status_text = resp.reason or ""

    total_ms = 0.0
    if resp and hasattr(resp, "timestamp_end") and resp.timestamp_end:
        total_ms = (resp.timestamp_end - req.timestamp_start) * 1000

    timestamp_ms = int(req.timestamp_start * 1000)

    meta = TraceMeta(
        id=trace_id,
        timestamp=timestamp_ms,
        request=RequestMeta(
            method=req.method,
            url=req.pretty_url,
            headers=req_headers,
            body_file=f"{trace_id}_request.bin" if req_body else None,
            body_size=len(req_body),
        ),
        response=ResponseMeta(
            status=status,
            status_text=status_text,
            headers=resp_headers,
            body_file=f"{trace_id}_response.bin" if resp_body else None,
            body_size=len(resp_body),
        ),
        timing=TimingInfo(total_ms=total_ms),
        initiator=Initiator(type="proxy"),
    )
    return Trace(meta=meta, request_body=req_body, response_body=resp_body)


def ws_flow_to_connection(
    flow: HTTPFlow,
    ws_id: str,
    messages: list[WsMessage],
) -> WsConnection:
    """Convert mitmproxy WebSocket data to a WsConnection."""
    meta = WsConnectionMeta(
        id=ws_id,
        timestamp=int(flow.request.timestamp_start * 1000),
        url=flow.request.pretty_url,
        protocols=_extract_ws_protocols(flow),
        message_count=len(messages),
    )
    return WsConnection(meta=meta, messages=messages)


def _extract_ws_protocols(flow: HTTPFlow) -> list[str]:
    """Extract WebSocket sub-protocols from the handshake."""
    proto = str(flow.request.headers.get("Sec-WebSocket-Protocol", "") or "")  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    if proto:
        return [p.strip() for p in proto.split(",")]
    return []


def _domain_to_regex(pattern: str) -> str:
    """Convert a user-friendly domain pattern to a regex for mitmproxy.

    Handles common patterns:
    - Plain domain: ``api.example.com`` → ``api\\.example\\.com``
    - Wildcard prefix: ``*.example.com`` → ``.*\\.example\\.com``
    - Already valid regex is passed through unchanged.
    """
    # If it already compiles as valid regex, use it as-is
    try:
        re.compile(pattern)
        return pattern
    except re.error:
        pass

    # Likely a glob-style pattern — convert it
    # Replace leading "*." with ".*\." then escape the rest
    if pattern.startswith("*."):
        return ".*\\." + re.escape(pattern[2:])

    # Fallback: escape everything
    return re.escape(pattern)


def run_mitmproxy(
    port: int,
    addons: list[object],
    allow_hosts: list[str] | None = None,
) -> tuple[float, float]:
    """Shared mitmproxy boilerplate: create loop, DumpMaster, run in daemon thread.

    Returns (start_time, end_time) as epoch seconds.
    """
    from mitmproxy.options import Options
    from mitmproxy.tools.dump import DumpMaster

    loop = asyncio.new_event_loop()
    opts = Options(listen_port=port, mode=["regular"])
    if allow_hosts:
        regex_hosts = [_domain_to_regex(h) for h in allow_hosts]
        opts.update(allow_hosts=regex_hosts)  # pyright: ignore[reportUnknownMemberType]
    master = DumpMaster(opts, loop=loop)
    for addon in addons:
        master.addons.add(addon)  # pyright: ignore[reportUnknownMemberType]

    proxy_thread = threading.Thread(
        target=loop.run_until_complete,
        args=(master.run(),),
        daemon=True,
    )
    proxy_thread.start()

    start_time = time.time()

    def _shutdown() -> None:
        loop.call_soon_threadsafe(master.shutdown)
        proxy_thread.join(timeout=10)

    def _sigint_handler(signum: int, frame: FrameType | None) -> None:
        _shutdown()

    signal.signal(signal.SIGINT, _sigint_handler)

    while proxy_thread.is_alive():
        proxy_thread.join(timeout=1)

    end_time = time.time()
    return start_time, end_time
