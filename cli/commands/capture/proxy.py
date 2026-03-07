"""MITM proxy capture command: CaptureAddon + proxy CLI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
import uuid

import click

if TYPE_CHECKING:
    from mitmproxy.http import HTTPFlow

from cli.commands.capture._mitm_gql_injection import inject_typename_into_flow
from cli.commands.capture._mitmproxy import (
    flow_to_trace,
    run_mitmproxy,
    ws_flow_to_connection,
)
from cli.commands.capture.types import CaptureBundle, Trace, WsConnection, WsMessage
from cli.formats.capture_bundle import (
    AppInfo,
    CaptureManifest,
    CaptureStats,
    Timeline,
    TimelineEvent,
    WsMessageMeta,
)
from cli.helpers.storage import store_capture


class CaptureAddon:
    """mitmproxy addon that collects flows into Trace/WsConnection objects.

    Automatically injects ``__typename`` into GraphQL queries to ensure
    response objects carry their type names for analysis.
    """

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

    def request(self, flow: HTTPFlow) -> None:
        """Intercept requests to inject __typename into GraphQL queries."""
        inject_typename_into_flow(flow)

    def response(self, flow: HTTPFlow) -> None:
        """Called when a full HTTP response has been received."""
        if flow.websocket:
            return

        self._trace_counter += 1
        trace_id = f"t_{self._trace_counter:04d}"
        trace = flow_to_trace(flow, trace_id)
        self.traces.append(trace)
        self.domains_seen.add(flow.request.host)

    def websocket_start(self, flow: HTTPFlow) -> None:
        """Called when a WebSocket connection is established."""
        self._ws_counter += 1
        ws_id = f"ws_{self._ws_counter:04d}"
        self._flow_ws_ids[flow.id] = ws_id
        self._ws_msg_counters[ws_id] = 0
        self._ws_messages[ws_id] = []
        self._ws_flows[ws_id] = flow
        self.domains_seen.add(flow.request.host)

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

    def websocket_end(self, flow: HTTPFlow) -> None:
        """Called when a WebSocket connection closes."""
        ws_id = self._flow_ws_ids.get(flow.id)
        if ws_id is None:
            return

        messages = self._ws_messages.get(ws_id, [])
        conn = ws_flow_to_connection(flow, ws_id, messages)
        self.ws_connections.append(conn)

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


def run_proxy_to_storage(
    port: int,
    app_name: str,
    allow_hosts: list[str] | None = None,
) -> tuple[CaptureStats, Path]:
    """Start a MITM proxy, capture traffic, and store in managed storage.

    Args:
        port: Proxy listen port.
        app_name: App name for managed storage.
        allow_hosts: Only intercept these host patterns (regex).

    Returns:
        (CaptureStats, capture_dir) on success.
    """
    addon = CaptureAddon()
    start_time, end_time = run_mitmproxy(port, [addon], allow_hosts=allow_hosts)

    bundle = addon.build_bundle(app_name, start_time, end_time)
    cap_dir = store_capture(bundle, app_name)

    return bundle.manifest.stats, cap_dir


@click.command()
@click.option("-a", "--app", "app_name", default=None, help="App name for storage")
@click.option("-p", "--port", default=8080, help="Proxy listen port")
@click.option(
    "-d",
    "--domain",
    "domains",
    multiple=True,
    help="Only intercept these domains (e.g. '*.example.com'). Can be repeated.",
)
def proxy_cmd(app_name: str | None, port: int, domains: tuple[str, ...]) -> None:
    """Start a MITM proxy to capture traffic into managed storage.

    Without -d, intercepts all domains. With -d, only matching domains.
    """
    from cli.helpers.console import console

    if app_name is None:
        app_name = click.prompt("App name")

    if not app_name:
        raise click.ClickException("App name is required.")

    allow_hosts = list(domains) if domains else None

    console.print(f"[bold]Starting MITM proxy on port {port}[/bold]")
    console.print(f"  App: {app_name}")
    if allow_hosts:
        console.print(f"  Domains: {', '.join(allow_hosts)}")
    else:
        console.print("  Intercepting all domains")

    click.echo("\n  Capturing... press Ctrl+C to stop.\n")

    stats, cap_dir = run_proxy_to_storage(port, app_name, allow_hosts=allow_hosts)
    console.print()
    console.print(f"[green]Capture stored in {cap_dir}[/green]")
    console.print(
        f"  {stats.trace_count} HTTP traces, "
        f"{stats.ws_connection_count} WS connections, "
        f"{stats.ws_message_count} WS messages"
    )
