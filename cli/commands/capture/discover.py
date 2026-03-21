"""CLI command: spectral capture discover."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
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
            if sni not in self.domains:
                console.print(f"  {sni}")
            self.domains[sni] = self.domains.get(sni, 0) + 1
        data.ignore_connection = True


def _run_discover(port: int, mode: str = "regular") -> dict[str, int]:
    """Start a proxy in discovery mode: log domains without MITM.

    All TLS connections pass through untouched. The addon records
    SNI hostnames with request counts.

    Args:
        port: Proxy listen port.
        mode: mitmproxy mode string (e.g. ``"regular"`` or ``"wireguard:…"``).

    Returns:
        Dict of domain → request count.
    """
    addon = DiscoveryAddon()
    block_quic = mode != "regular"
    run_mitmproxy(port, [addon], mode=mode, block_quic=block_quic)

    return addon.domains


@click.command()
@click.option("-p", "--port", default=8080, help="Proxy listen port")
@click.option(
    "--wireguard",
    "--wg",
    "wireguard",
    is_flag=True,
    default=False,
    help="Use WireGuard VPN mode (captures traffic from apps that ignore system proxy).",
)
def discover(port: int, wireguard: bool) -> None:
    """Discover domains without intercepting traffic.

    Runs a passthrough proxy that logs TLS SNI hostnames and plain
    HTTP hosts. No MITM — all connections pass through untouched.

    Use --wireguard for apps that bypass the system proxy (e.g. Flutter).
    """
    from cli.commands.capture._wireguard import (
        build_wireguard_config,
        display_wireguard_config,
    )

    mode = "regular"

    if wireguard:
        config_text, mode = build_wireguard_config(port)
        display_wireguard_config(config_text)
        console.print(
            "\n[bold yellow]Instructions:[/bold yellow]\n"
            "  1. Install the WireGuard app on your device\n"
            "  2. Scan the QR code or import the config above\n"
            "  3. Activate the WireGuard tunnel\n"
        )

    console.print(f"[bold]Starting domain discovery on port {port}[/bold]")
    if wireguard:
        console.print("  Mode: WireGuard VPN")
    console.print("  No MITM — logging domains only.")
    click.echo("\n  Listening... press Ctrl+C to stop.\n")

    domains = _run_discover(port, mode=mode)

    if domains:
        console.print(f"\n  Discovered {len(domains)} domain(s):\n")
        for domain, count in sorted(domains.items(), key=lambda x: -x[1]):
            console.print(f"    {count:4d}  {domain}")
        top = sorted(domains.items(), key=lambda x: -x[1])[0][0]
        console.print("\n  Re-run with -d to capture specific domains, or -e to exclude:")
        console.print(f"    spectral capture proxy -d '{top}'")
        console.print(f"    spectral capture proxy -e '*.google.com'\n")
    else:
        console.print("\n  No domains discovered.\n")
