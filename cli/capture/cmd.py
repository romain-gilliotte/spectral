"""CLI command for inspecting capture bundles."""

from __future__ import annotations

import json

import click
from rich.table import Table

from cli.capture.models import CaptureBundle
from cli.console import console


def _truncate(s: str, max_len: int) -> str:
    """Truncate a string to max_len, adding '...' if needed."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."



@click.command()
@click.argument("capture_path", type=click.Path(exists=True))
@click.option("--trace", "trace_id", default=None, help="Show details for a specific trace")
def inspect(capture_path: str, trace_id: str | None) -> None:
    """Inspect a capture bundle."""
    from cli.capture.loader import load_bundle

    bundle = load_bundle(capture_path)

    if trace_id:
        _inspect_trace(bundle, trace_id)
    else:
        _inspect_summary(bundle)


def _inspect_summary(bundle: CaptureBundle) -> None:
    """Print a summary of the capture bundle."""
    m = bundle.manifest
    console.print("[bold]Capture Bundle Summary[/bold]")
    console.print(f"  Capture ID: {m.capture_id}")
    console.print(f"  Created: {m.created_at}")
    console.print(f"  App: {m.app.name} ({m.app.base_url})")
    if m.browser:
        console.print(f"  Browser: {m.browser.name} {m.browser.version}")
    console.print(f"  Capture method: {m.capture_method}")
    console.print(f"  Duration: {m.duration_ms}ms")
    console.print()

    table = Table(title="Statistics")
    table.add_column("Type", style="cyan")
    table.add_column("Count", justify="right")
    table.add_row("HTTP Traces", str(len(bundle.traces)))
    table.add_row("WS Connections", str(len(bundle.ws_connections)))
    ws_msg_count = sum(len(ws.messages) for ws in bundle.ws_connections)
    table.add_row("WS Messages", str(ws_msg_count))
    table.add_row("UI Contexts", str(len(bundle.contexts)))
    table.add_row("Timeline Events", str(len(bundle.timeline.events)))
    console.print(table)
    console.print()

    # List traces
    if bundle.traces:
        trace_table = Table(title="Traces")
        trace_table.add_column("ID", style="cyan")
        trace_table.add_column("Method")
        trace_table.add_column("URL")
        trace_table.add_column("Status", justify="right")
        trace_table.add_column("Time (ms)", justify="right")

        for trace in bundle.traces:
            trace_table.add_row(
                trace.meta.id,
                trace.meta.request.method,
                _truncate(trace.meta.request.url, 60),
                str(trace.meta.response.status),
                f"{trace.meta.timing.total_ms:.0f}",
            )
        console.print(trace_table)


def _inspect_trace(bundle: CaptureBundle, trace_id: str) -> None:
    """Print details for a specific trace."""
    trace = bundle.get_trace(trace_id)
    if not trace:
        console.print(f"[red]Trace {trace_id} not found[/red]")
        return

    m = trace.meta
    console.print(f"[bold]Trace: {m.id}[/bold]")
    console.print(f"  Timestamp: {m.timestamp}")
    console.print(f"  Type: {m.type}")
    console.print()

    console.print("[bold]Request[/bold]")
    console.print(f"  {m.request.method} {m.request.url}")
    for h in m.request.headers:
        console.print(f"  {h.name}: {h.value}")
    if trace.request_body:
        console.print(f"  Body ({len(trace.request_body)} bytes):")
        _print_body(trace.request_body)
    console.print()

    console.print("[bold]Response[/bold]")
    console.print(f"  {m.response.status} {m.response.status_text}")
    for h in m.response.headers:
        console.print(f"  {h.name}: {h.value}")
    if trace.response_body:
        console.print(f"  Body ({len(trace.response_body)} bytes):")
        _print_body(trace.response_body)
    console.print()

    console.print("[bold]Timing[/bold]")
    t = m.timing
    console.print(f"  DNS: {t.dns_ms}ms, Connect: {t.connect_ms}ms, TLS: {t.tls_ms}ms")
    console.print(f"  Send: {t.send_ms}ms, Wait: {t.wait_ms}ms, Receive: {t.receive_ms}ms")
    console.print(f"  Total: {t.total_ms}ms")

    if m.context_refs:
        console.print(f"\n[bold]Context refs:[/bold] {', '.join(m.context_refs)}")


def _print_body(body: bytes) -> None:
    """Pretty-print a body payload."""
    try:
        text = body.decode("utf-8")
        try:
            data = json.loads(text)
            console.print_json(json.dumps(data))
        except json.JSONDecodeError:
            console.print(f"  {_truncate(text, 500)}")
    except UnicodeDecodeError:
        console.print(f"  <binary, {len(body)} bytes>")
