"""CLI commands for capture: inspect bundles, run MITM proxy, discover domains."""

from __future__ import annotations

from pathlib import Path

import click

from cli.helpers.console import console


@click.group()
def capture() -> None:
    """Capture tools: inspect bundles, run MITM proxy."""


@capture.command()
@click.argument("capture_path", type=click.Path(exists=True))
@click.option(
    "--trace", "trace_id", default=None, help="Show details for a specific trace"
)
def inspect(capture_path: str, trace_id: str | None) -> None:
    """Inspect a capture bundle."""
    from cli.commands.capture.inspect import inspect_summary, inspect_trace
    from cli.commands.capture.loader import load_bundle

    bundle = load_bundle(capture_path)

    if trace_id:
        inspect_trace(bundle, trace_id)
    else:
        inspect_summary(bundle)


@capture.command()
@click.option("-p", "--port", default=8080, help="Proxy listen port")
@click.option("-o", "--output", default=None, help="Output bundle path (.zip)")
@click.option(
    "-d",
    "--domain",
    "domains",
    multiple=True,
    help="Only intercept these domains (regex). Can be repeated.",
)
def proxy(port: int, output: str | None, domains: tuple[str, ...]) -> None:
    """Start a MITM proxy to capture traffic.

    Without -d, intercepts all domains. With -d, only matching domains.
    """
    from cli.commands.capture.proxy import run_proxy

    allow_hosts = list(domains) if domains else None
    output_path = Path(output or "capture.zip")
    app_name = output_path.stem if output else "app"

    console.print(f"[bold]Starting MITM proxy on port {port}[/bold]")
    if allow_hosts:
        console.print(f"  Domains: {', '.join(allow_hosts)}")
    else:
        console.print("  Intercepting all domains")
    console.print(f"  Output:  {output_path}")

    click.echo("\n  Capturing... press Ctrl+C to stop.\n")

    stats = run_proxy(port, output_path, app_name, allow_hosts=allow_hosts)
    console.print()
    console.print(f"[green]Capture bundle written to {output_path}[/green]")
    console.print(
        f"  {stats.trace_count} HTTP traces, {stats.ws_connection_count} WS connections, {stats.ws_message_count} WS messages"
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
