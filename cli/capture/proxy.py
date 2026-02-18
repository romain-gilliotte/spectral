"""Generic MITM proxy capture engine, producing a CaptureBundle."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import signal
from typing import TYPE_CHECKING
import uuid

import click

if TYPE_CHECKING:
    from mitmproxy.http import Headers as mitmproxy_Headers, HTTPFlow
    from mitmproxy.tls import ClientHelloData

from cli.capture.loader import write_bundle
from cli.capture.types import CaptureBundle, Trace, WsConnection, WsMessage
from cli.formats.capture_bundle import (
    AppInfo,
    CaptureManifest,
    CaptureStats,
    Header,
    RequestMeta,
    ResponseMeta,
    Timeline,
    TimelineEvent,
    TimingInfo,
    WsConnectionMeta,
    WsMessageMeta,
)


def _ensure_mitmproxy() -> None:
    """Lazy-import mitmproxy, raising a clear error if not installed."""
    try:
        import mitmproxy as _mitmproxy  # noqa: F401

        del _mitmproxy
    except ImportError:
        raise ImportError(
            "mitmproxy is required for proxy capture.\n"
            "Install it with: uv add 'spectral[proxy]'\n"
            "  or: pip install mitmproxy>=10.0"
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

    from cli.formats.capture_bundle import Initiator, TraceMeta

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


class DiscoveryAddon:
    """mitmproxy addon that logs domains without MITM (passthrough TLS)."""

    def __init__(self) -> None:
        self.domains: dict[str, int] = {}  # domain → request count

    def tls_clienthello(self, data: ClientHelloData) -> None:
        """Skip MITM — just log the SNI and pass through."""
        sni = data.context.client.sni
        if sni:
            self.domains[sni] = self.domains.get(sni, 0) + 1
            click.echo(f"  {sni}  ({self.domains[sni]})")
        data.ignore_connection = True

    def request(self, flow: HTTPFlow) -> None:
        """Log plain HTTP requests (non-TLS)."""
        host = flow.request.host
        if host:
            self.domains[host] = self.domains.get(host, 0) + 1
            click.echo(f"  {host}  ({self.domains[host]})")


class CaptureAddon:
    """mitmproxy addon that collects flows into Trace/WsConnection objects."""

    def __init__(self) -> None:
        self.traces: list[Trace] = []
        self.ws_connections: list[WsConnection] = []
        self._trace_counter: int = 0
        self._ws_counter: int = 0
        self._ws_msg_counters: dict[str, int] = {}
        self._ws_messages: dict[str, list[WsMessage]] = {}
        self._ws_flows: dict[str, HTTPFlow] = {}
        self._flow_ws_ids: dict[str, str] = {}  # flow.id -> ws_id
        self.domains_seen: set[str] = set()

    def response(self, flow: HTTPFlow) -> None:
        """Called when a full HTTP response has been received."""
        if flow.websocket:
            return

        self._trace_counter += 1
        trace_id = f"t_{self._trace_counter:04d}"
        trace = flow_to_trace(flow, trace_id)
        self.traces.append(trace)
        self.domains_seen.add(flow.request.host)

        status = flow.response.status_code if flow.response else "?"
        click.echo(
            f"  {trace_id}  {flow.request.method:<6} {status}  {flow.request.pretty_url}"
        )

    def websocket_start(self, flow: HTTPFlow) -> None:
        """Called when a WebSocket connection is established."""
        self._ws_counter += 1
        ws_id = f"ws_{self._ws_counter:04d}"
        self._flow_ws_ids[flow.id] = ws_id
        self._ws_msg_counters[ws_id] = 0
        self._ws_messages[ws_id] = []
        self._ws_flows[ws_id] = flow
        self.domains_seen.add(flow.request.host)

        click.echo(f"  {ws_id}  WS OPEN  {flow.request.pretty_url}")

    def websocket_message(self, flow: HTTPFlow) -> None:
        """Called for each WebSocket message."""
        ws_id = self._flow_ws_ids.get(flow.id)
        if ws_id is None:
            return

        from mitmproxy.websocket import WebSocketMessage

        assert flow.websocket is not None
        msg: WebSocketMessage = flow.websocket.messages[-1]
        self._ws_msg_counters[ws_id] += 1
        msg_num = self._ws_msg_counters[ws_id]
        msg_id = f"{ws_id}_m{msg_num:03d}"

        direction = "send" if msg.from_client else "receive"
        payload = msg.content or b""
        opcode = "text" if msg.is_text else "binary"
        timestamp_ms = (
            int(msg.timestamp * 1000)
            if hasattr(msg, "timestamp") and msg.timestamp
            else int(flow.request.timestamp_start * 1000)
        )

        ws_msg = WsMessage(
            meta=WsMessageMeta(
                id=msg_id,
                connection_ref=ws_id,
                timestamp=timestamp_ms,
                direction=direction,
                opcode=opcode,
                payload_file=f"{msg_id}.bin" if payload else None,
                payload_size=len(payload),
            ),
            payload=payload,
        )
        self._ws_messages[ws_id].append(ws_msg)

        arrow = ">>>" if direction == "send" else "<<<"
        click.echo(f"  {msg_id}  WS {arrow}  {len(payload)}B {opcode}")

    def websocket_end(self, flow: HTTPFlow) -> None:
        """Called when a WebSocket connection closes."""
        ws_id = self._flow_ws_ids.get(flow.id)
        if ws_id is None:
            return

        messages = self._ws_messages.get(ws_id, [])
        conn = ws_flow_to_connection(flow, ws_id, messages)
        self.ws_connections.append(conn)

        click.echo(f"  {ws_id}  WS CLOSE ({len(messages)} messages)")

    def build_bundle(
        self, app_name: str, start_time: float, end_time: float
    ) -> CaptureBundle:
        """Assemble all captured data into a CaptureBundle."""
        # Finalize any WS connections that didn't close cleanly
        finalized_ws_ids = {ws.meta.id for ws in self.ws_connections}
        for ws_id, flow in self._ws_flows.items():
            if ws_id not in finalized_ws_ids:
                messages = self._ws_messages.get(ws_id, [])
                conn = ws_flow_to_connection(flow, ws_id, messages)
                self.ws_connections.append(conn)

        base_url = ""
        if self.domains_seen:
            base_url = f"https://{sorted(self.domains_seen)[0]}"

        duration_ms = int((end_time - start_time) * 1000)
        ws_msg_count = sum(len(ws.messages) for ws in self.ws_connections)

        manifest = CaptureManifest(
            capture_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            app=AppInfo(name=app_name, base_url=base_url, title=app_name),
            browser=None,
            extension_version=None,
            duration_ms=duration_ms,
            stats=CaptureStats(
                trace_count=len(self.traces),
                ws_connection_count=len(self.ws_connections),
                ws_message_count=ws_msg_count,
                context_count=0,
            ),
            capture_method="proxy",
        )

        events: list[TimelineEvent] = []
        for t in self.traces:
            events.append(
                TimelineEvent(timestamp=t.meta.timestamp, type="trace", ref=t.meta.id)
            )
        for ws in self.ws_connections:
            events.append(
                TimelineEvent(
                    timestamp=ws.meta.timestamp, type="ws_open", ref=ws.meta.id
                )
            )
            for msg in ws.messages:
                events.append(
                    TimelineEvent(
                        timestamp=msg.meta.timestamp, type="ws_message", ref=msg.meta.id
                    )
                )
        events.sort(key=lambda e: e.timestamp)

        return CaptureBundle(
            manifest=manifest,
            traces=self.traces,
            ws_connections=self.ws_connections,
            contexts=[],
            timeline=Timeline(events=events),
        )


def run_proxy(
    port: int,
    output_path: Path | None,
    app_name: str,
    allow_hosts: list[str] | None = None,
) -> CaptureStats | None:
    """Start a MITM proxy, capture traffic, and write a bundle on stop.

    This is the generic proxy engine — no device-specific setup.
    The proxy runs until the user presses Ctrl+C.

    Args:
        port: Proxy listen port.
        output_path: Path to write the capture bundle .zip.
        app_name: Name for the captured app in the manifest.
        allow_hosts: Only intercept these host patterns (regex).
            Other traffic passes through without MITM.

    Returns:
        CaptureStats on success, None if cancelled.
    """
    _ensure_mitmproxy()

    import asyncio
    import threading
    import time

    from mitmproxy.options import Options
    from mitmproxy.tools.dump import DumpMaster

    discovery_mode = not allow_hosts

    if discovery_mode:
        discovery_addon = DiscoveryAddon()
        addon = None
    else:
        discovery_addon = None
        addon = CaptureAddon()

    loop = asyncio.new_event_loop()
    opts = Options(listen_port=port, mode=["regular"])
    if allow_hosts:
        opts.update(allow_hosts=allow_hosts)  # pyright: ignore[reportUnknownMemberType]
    master = DumpMaster(opts, loop=loop)
    master.addons.add(discovery_addon if discovery_mode else addon)  # pyright: ignore[reportUnknownMemberType]

    proxy_thread = threading.Thread(
        target=loop.run_until_complete,
        args=(master.run(),),
        daemon=True,
    )
    proxy_thread.start()

    def _shutdown():
        loop.call_soon_threadsafe(master.shutdown)
        proxy_thread.join(timeout=10)

    if discovery_mode:
        click.echo("\n  Discovery mode — no MITM, just logging domains.")
        click.echo("  Re-run with -d <domain> to capture traffic.\n")
        click.echo("  Listening... press Ctrl+C to stop.\n")
    else:
        click.echo("\n  Capturing... press Ctrl+C to stop.\n")

    start_time = time.time()

    signal.signal(signal.SIGINT, lambda *_: _shutdown())  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]

    while proxy_thread.is_alive():
        proxy_thread.join(timeout=1)

    end_time = time.time()

    if discovery_mode:
        assert discovery_addon is not None
        domains = discovery_addon.domains
        if domains:
            click.echo(f"\n  Discovered {len(domains)} domain(s):\n")
            for domain, count in sorted(domains.items(), key=lambda x: -x[1]):
                click.echo(f"    {count:4d}  {domain}")
            click.echo("\n  Re-run with -d to capture specific domains, e.g.:")
            top = sorted(domains.items(), key=lambda x: -x[1])[0][0]
            click.echo(f"    spectral capture proxy -d '{top}'\n")
        else:
            click.echo("\n  No domains discovered.\n")
        return None

    assert addon is not None
    assert output_path is not None
    bundle = addon.build_bundle(app_name, start_time, end_time)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_bundle(bundle, output_path)

    return bundle.manifest.stats
