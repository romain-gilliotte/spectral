"""CLI command: spectral capture discover."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from mitmproxy.http import HTTPFlow
    from mitmproxy.tls import ClientHelloData

from cli.commands.capture._mitmproxy import run_mitmproxy
from cli.helpers.console import console


class DiscoveryAddon:
    """mitmproxy addon that logs domains without MITM (passthrough TLS)."""

    def __init__(self) -> None:
        self.domains: dict[str, int] = {}  # domain → request count

    def tls_clienthello(self, data: ClientHelloData) -> None:
        """Skip MITM — just log the SNI and pass through."""
        sni = data.context.client.sni
        if sni:
            self.domains[sni] = self.domains.get(sni, 0) + 1
        data.ignore_connection = True

    def request(self, flow: HTTPFlow) -> None:
        """Log plain HTTP requests (non-TLS)."""
        host = flow.request.host
        if host:
            self.domains[host] = self.domains.get(host, 0) + 1


def _run_discover(port: int) -> dict[str, int]:
    """Start a proxy in discovery mode: log domains without MITM.

    All TLS connections pass through untouched. The addon records
    SNI hostnames (and plain HTTP hosts) with request counts.

    Args:
        port: Proxy listen port.

    Returns:
        Dict of domain → request count.
    """
    addon = DiscoveryAddon()
    run_mitmproxy(port, [addon])

    return addon.domains


@click.command()
@click.option("-p", "--port", default=8080, help="Proxy listen port")
def discover(port: int) -> None:
    """Discover domains without intercepting traffic.

    Runs a passthrough proxy that logs TLS SNI hostnames and plain
    HTTP hosts. No MITM — all connections pass through untouched.
    """
    console.print(f"[bold]Starting domain discovery on port {port}[/bold]")
    console.print("  No MITM — logging domains only.")
    click.echo("\n  Listening... press Ctrl+C to stop.\n")

    domains = _run_discover(port)

    if domains:
        console.print(f"\n  Discovered {len(domains)} domain(s):\n")
        for domain, count in sorted(domains.items(), key=lambda x: -x[1]):
            console.print(f"    {count:4d}  {domain}")
        top = sorted(domains.items(), key=lambda x: -x[1])[0][0]
        console.print("\n  Re-run with -d to capture specific domains, e.g.:")
        console.print(f"    spectral capture proxy -d '{top}'\n")
    else:
        console.print("\n  No domains discovered.\n")
