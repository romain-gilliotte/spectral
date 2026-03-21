"""MITM proxy capture command: CaptureAddon + proxy CLI."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import TYPE_CHECKING
import uuid

import click

if TYPE_CHECKING:
    from mitmproxy.http import HTTPFlow

from cli.commands.capture._mitm_gql_injection import inject_typename_into_flow
from cli.commands.capture._mitmproxy import flow_to_trace, run_mitmproxy
from cli.commands.capture.types import CaptureBundle, Trace
from cli.formats.capture_bundle import (
    AppInfo,
    CaptureManifest,
    CaptureStats,
    Timeline,
    TimelineEvent,
)
import cli.helpers.storage as storage

# ---------------------------------------------------------------------------
# App providers: who is generating the traffic?
# ---------------------------------------------------------------------------

class FixedAppProvider:
    """Always returns the same app name (used with ``-a``)."""

    def __init__(self, app_name: str) -> None:
        self._app_name = app_name

    @property
    def current(self) -> str | None:
        return self._app_name

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class ForegroundAppPoller:
    """Polls ADB for the foreground Android app in a background thread."""

    def __init__(self, interval: float = 1.0) -> None:
        self._interval = interval
        self._current: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)

    @property
    def current(self) -> str | None:
        return self._current

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _poll(self) -> None:
        from cli.commands.android.external_tools.adb import get_foreground_package

        while not self._stop.is_set():
            self._current = get_foreground_package()
            self._stop.wait(self._interval)


AppProvider = FixedAppProvider | ForegroundAppPoller


def _package_to_app_name(package: str) -> str:
    """Convert an Android package name to a valid spectral app name.

    Replaces dots with dashes and lowercases to match the
    ``[a-z0-9]+(-[a-z0-9]+)*`` pattern required by storage.
    """
    return package.lower().replace(".", "-").replace("_", "-")


# ---------------------------------------------------------------------------
# mitmproxy addon
# ---------------------------------------------------------------------------

class CaptureAddon:
    """mitmproxy addon that collects HTTP flows into Trace objects.

    Automatically injects ``__typename`` into GraphQL queries to ensure
    response objects carry their type names for analysis.
    """

    def __init__(self, app_provider: AppProvider) -> None:
        self.traces: list[Trace] = []
        self._trace_counter: int = 0
        self.domains_seen: set[str] = set()
        self._app_provider = app_provider
        self._last_logged_app: str | None = None

    def request(self, flow: HTTPFlow) -> None:
        """Intercept requests to inject __typename into GraphQL queries."""
        inject_typename_into_flow(flow)

    def response(self, flow: HTTPFlow) -> None:
        """Called when a full HTTP response has been received."""
        if flow.websocket:
            return
        if flow.request.method == "OPTIONS":
            return

        self._trace_counter += 1
        trace_id = f"t_{self._trace_counter:04d}"
        trace = flow_to_trace(flow, trace_id)
        current = self._app_provider.current
        trace.meta.app_package = current
        if current and current != self._last_logged_app:
            from cli.helpers.console import console

            console.print(f"  [dim]App:[/dim] {current}")
            self._last_logged_app = current
        self.traces.append(trace)
        self.domains_seen.add(flow.request.host)

    def build_bundles_by_app(
        self, start_time: float, end_time: float
    ) -> dict[str, CaptureBundle]:
        """Group traces by ``app_package`` and build one bundle per app.

        Traces without an ``app_package`` are grouped under ``"unknown"``.
        """
        groups: dict[str, list[Trace]] = defaultdict(list)
        for trace in self.traces:
            key = trace.meta.app_package or "unknown"
            groups[key].append(trace)

        duration_ms = int((end_time - start_time) * 1000)
        bundles: dict[str, CaptureBundle] = {}

        for package, traces in groups.items():
            app_name = _package_to_app_name(package) if package != "unknown" else "unknown"
            domains = {
                trace.meta.request.url.split("/")[2]
                for trace in traces
                if "/" in trace.meta.request.url
            }
            base_url = f"https://{sorted(domains)[0]}" if domains else ""

            manifest = CaptureManifest(
                capture_id=str(uuid.uuid4()),
                created_at=datetime.now(timezone.utc).isoformat(),
                app=AppInfo(name=app_name, base_url=base_url, title=package),
                browser=None,
                extension_version=None,
                duration_ms=duration_ms,
                stats=CaptureStats(trace_count=len(traces)),
                capture_method="proxy",
            )

            events = [
                TimelineEvent(timestamp=t.meta.timestamp, type="trace", ref=t.meta.id)
                for t in traces
            ]
            events.sort(key=lambda e: e.timestamp)

            bundles[package] = CaptureBundle(
                manifest=manifest,
                traces=traces,
                ws_connections=[],
                contexts=[],
                timeline=Timeline(events=events),
            )

        return bundles


# ---------------------------------------------------------------------------
# Run proxy and store captures
# ---------------------------------------------------------------------------

def _run_proxy_and_store(
    port: int,
    app_provider: AppProvider,
    allow_hosts: list[str] | None = None,
    ignore_hosts: list[str] | None = None,
    mode: str = "regular",
) -> dict[str, tuple[CaptureStats, Path]]:
    """Run the MITM proxy, then store one capture per detected app.

    Returns dict of package_name → (stats, capture_dir).
    """
    app_provider.start()
    addon = CaptureAddon(app_provider)
    block_quic = mode != "regular"
    start_time, end_time = run_mitmproxy(
        port,
        [addon],
        allow_hosts=allow_hosts,
        ignore_hosts=ignore_hosts,
        mode=mode,
        block_quic=block_quic,
    )
    app_provider.stop()

    bundles = addon.build_bundles_by_app(start_time, end_time)
    results: dict[str, tuple[CaptureStats, Path]] = {}
    for package, bundle in bundles.items():
        app_name = bundle.manifest.app.name
        cap_dir = storage.store_capture(bundle, app_name)
        results[package] = (bundle.manifest.stats, cap_dir)

    return results


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

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
@click.option(
    "-e",
    "--exclude",
    "excludes",
    multiple=True,
    help="Exclude these domains from MITM (pass through). Can be repeated.",
)
@click.option(
    "--wireguard",
    "--wg",
    "wireguard",
    is_flag=True,
    default=False,
    help="Use WireGuard VPN mode (captures traffic from apps that ignore system proxy).",
)
@click.option(
    "--autodetect-app",
    is_flag=True,
    default=False,
    help="Auto-detect foreground Android app via ADB (replaces -a).",
)
def proxy_cmd(
    app_name: str | None,
    port: int,
    domains: tuple[str, ...],
    excludes: tuple[str, ...],
    wireguard: bool,
    autodetect_app: bool,
) -> None:
    """Start a MITM proxy to capture traffic into managed storage.

    Without -d, intercepts all domains. With -d, only matching domains.
    Use -e to exclude specific domains from MITM (e.g. SSO providers).

    Use --wireguard for apps that bypass the system proxy (e.g. Flutter).
    Use --autodetect-app to auto-detect the foreground Android app via ADB
    and store captures per app (no -a required).
    """
    from cli.helpers.console import console

    if autodetect_app and app_name is not None:
        raise click.UsageError("Cannot use both -a/--app and --autodetect-app.")

    if autodetect_app:
        app_provider: AppProvider = ForegroundAppPoller()
    else:
        if app_name is not None:
            storage.validate_app_name(app_name)
        else:
            while True:
                app_name = click.prompt("App name")
                if not app_name:
                    click.echo("App name is required.")
                    continue
                try:
                    storage.validate_app_name(app_name)
                    break
                except click.ClickException as exc:
                    click.echo(exc.format_message())
        app_provider = FixedAppProvider(app_name)

    allow_hosts = list(domains) if domains else None
    ignore_hosts = list(excludes) if excludes else None
    mode = "regular"

    if wireguard:
        from cli.commands.capture._wireguard import (
            build_wireguard_config,
            display_wireguard_config,
        )

        config_text, mode = build_wireguard_config(port)
        display_wireguard_config(config_text)
        console.print(
            "\n[bold yellow]Instructions:[/bold yellow]\n"
            "  1. Install the WireGuard app on your device\n"
            "  2. Scan the QR code or import the config above\n"
            "  3. Activate the WireGuard tunnel\n"
        )

    console.print(f"[bold]Starting MITM proxy on port {port}[/bold]")
    if wireguard:
        console.print("  Mode: WireGuard VPN")
    if autodetect_app:
        console.print("  App: auto-detect via ADB")
    else:
        console.print(f"  App: {app_name}")
    if allow_hosts:
        console.print(f"  Domains: {', '.join(allow_hosts)}")
    else:
        console.print("  Intercepting all domains")
    if ignore_hosts:
        console.print(f"  Excluded: {', '.join(ignore_hosts)}")

    click.echo("\n  Capturing... press Ctrl+C to stop.\n")

    results = _run_proxy_and_store(
        port, app_provider, allow_hosts=allow_hosts, ignore_hosts=ignore_hosts, mode=mode
    )

    console.print()
    if not results:
        console.print("[yellow]No traffic captured.[/yellow]")
        return
    total_traces = sum(s.trace_count for s, _ in results.values())
    console.print(
        f"[green]Captured {total_traces} traces across {len(results)} app(s):[/green]"
    )
    for package, (stats, cap_dir) in sorted(results.items()):
        console.print(f"\n  [bold]{package}[/bold]")
        console.print(f"    {stats.trace_count} HTTP traces → {cap_dir}")
