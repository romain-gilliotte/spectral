"""CLI commands for capture: add, list, show, inspect, proxy, discover."""

from __future__ import annotations

import click

from cli.helpers.console import console


@click.group()
def capture() -> None:
    """Capture tools: import bundles, inspect, run MITM proxy."""


@capture.command()
@click.argument("zip_file", type=click.Path(exists=True))
@click.option("-a", "--app", "app_name", default=None, help="App name for storage")
def add(zip_file: str, app_name: str | None) -> None:
    """Import a ZIP bundle from the Chrome extension into managed storage."""
    from cli.commands.capture.loader import load_bundle
    from cli.helpers.storage import (
        DuplicateCaptureError,
        import_capture,
        list_captures,
        slugify,
    )

    if app_name is None:
        bundle = load_bundle(zip_file)
        suggested = slugify(bundle.manifest.app.name)
        app_name = click.prompt("App name", default=suggested)

    if not app_name:
        raise click.ClickException("App name is required.")

    try:
        cap_dir = import_capture(zip_file, app_name)
    except DuplicateCaptureError as exc:
        console.print(f"[yellow]Capture already imported ({exc.capture_id}). Skipping.[/yellow]")
        return

    cap_count = len(list_captures(app_name))

    console.print(f"[green]Imported into app '{app_name}'[/green]")
    console.print(f"  Capture dir: {cap_dir}")
    console.print(f"  Total captures: {cap_count}")


@capture.command("list")
def list_cmd() -> None:
    """List all known apps with capture counts."""
    from rich.table import Table

    from cli.helpers.storage import list_apps, list_captures

    apps = list_apps()
    if not apps:
        console.print("No apps found. Import a capture with 'spectral capture add <file.zip>'.")
        return

    table = Table(title="Apps")
    table.add_column("Name", style="cyan")
    table.add_column("Display Name")
    table.add_column("Captures", justify="right")
    table.add_column("Last Updated")

    for app in apps:
        cap_count = len(list_captures(app.name))
        table.add_row(app.name, app.display_name, str(cap_count), app.updated_at)

    console.print(table)


@capture.command()
@click.argument("app_name")
def show(app_name: str) -> None:
    """Show captures for an app."""
    from cli.commands.capture.loader import load_bundle_dir
    from cli.helpers.storage import list_captures, resolve_app

    resolve_app(app_name)
    caps = list_captures(app_name)

    if not caps:
        console.print(f"No captures for app '{app_name}'.")
        return

    console.print(f"[bold]App: {app_name}[/bold]  ({len(caps)} capture(s))\n")

    for i, cap_dir in enumerate(caps, 1):
        bundle = load_bundle_dir(cap_dir)
        m = bundle.manifest
        console.print(f"  [{i}] {cap_dir.name}")
        console.print(f"      Created: {m.created_at}  Method: {m.capture_method}")
        console.print(
            f"      {m.stats.trace_count} traces, "
            f"{m.stats.ws_connection_count} WS conns, "
            f"{m.stats.context_count} contexts"
        )


@capture.command()
@click.argument("app_name")
@click.option(
    "--trace", "trace_id", default=None, help="Show details for a specific trace"
)
def inspect(app_name: str, trace_id: str | None) -> None:
    """Inspect the latest capture for an app."""
    from cli.commands.capture.inspect import inspect_summary, inspect_trace
    from cli.commands.capture.loader import load_bundle_dir
    from cli.helpers.storage import latest_capture, resolve_app

    resolve_app(app_name)
    cap_dir = latest_capture(app_name)

    if cap_dir is None:
        console.print(f"No captures for app '{app_name}'.")
        return

    bundle = load_bundle_dir(cap_dir)

    if trace_id:
        inspect_trace(bundle, trace_id)
    else:
        inspect_summary(bundle)


@capture.command()
@click.option("-a", "--app", "app_name", default=None, help="App name for storage")
@click.option("-p", "--port", default=8080, help="Proxy listen port")
@click.option(
    "-d",
    "--domain",
    "domains",
    multiple=True,
    help="Only intercept these domains (e.g. '*.example.com'). Can be repeated.",
)
def proxy(app_name: str | None, port: int, domains: tuple[str, ...]) -> None:
    """Start a MITM proxy to capture traffic into managed storage.

    Without -d, intercepts all domains. With -d, only matching domains.
    """
    from cli.commands.capture.proxy import run_proxy_to_storage

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


@capture.command()
@click.option("-p", "--port", default=8080, help="Proxy listen port")
def discover(port: int) -> None:
    """Discover domains without intercepting traffic.

    Runs a passthrough proxy that logs TLS SNI hostnames and plain
    HTTP hosts. No MITM — all connections pass through untouched.
    """
    from cli.commands.capture.proxy import run_discover

    console.print(f"[bold]Starting domain discovery on port {port}[/bold]")
    console.print("  No MITM — logging domains only.")
    click.echo("\n  Listening... press Ctrl+C to stop.\n")

    domains = run_discover(port)

    if domains:
        console.print(f"\n  Discovered {len(domains)} domain(s):\n")
        for domain, count in sorted(domains.items(), key=lambda x: -x[1]):
            console.print(f"    {count:4d}  {domain}")
        top = sorted(domains.items(), key=lambda x: -x[1])[0][0]
        console.print("\n  Re-run with -d to capture specific domains, e.g.:")
        console.print(f"    spectral capture proxy -d '{top}'\n")
    else:
        console.print("\n  No domains discovered.\n")
