"""Shared WireGuard VPN mode helpers for capture commands."""

from __future__ import annotations

import json
import socket

from cli.helpers import storage
from cli.helpers.console import console


def get_local_ip() -> str:
    """Get the local IP address by connecting a UDP socket to an external host."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return str(ip)
    except OSError:
        return "127.0.0.1"


def build_wireguard_config(port: int) -> tuple[str, str]:
    """Generate or reuse WireGuard keys, return (client_config, mode_spec).

    On first run, generates key pairs and writes them to
    ``$SPECTRAL_HOME/wireguard.conf``.  On subsequent runs the existing
    keys are reused so the client tunnel config stays stable (no need to
    re-scan the QR code on the device).
    """
    from mitmproxy_rs.wireguard import genkey, pubkey

    conf_path = storage.store_root() / "wireguard.conf"
    conf_path.parent.mkdir(parents=True, exist_ok=True)

    if conf_path.exists():
        server_conf = json.loads(conf_path.read_text())
        server_private = server_conf["server_key"]
        client_private = server_conf["client_key"]
    else:
        server_private = genkey()
        client_private = genkey()
        server_conf = {
            "server_key": server_private,
            "client_key": client_private,
        }
        conf_path.write_text(json.dumps(server_conf, indent=4) + "\n")

    server_public = pubkey(server_private)
    local_ip = get_local_ip()

    client_config = (
        "[Interface]\n"
        f"PrivateKey = {client_private}\n"
        "Address = 10.0.0.1/32\n"
        "DNS = 10.0.0.53\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {server_public}\n"
        f"Endpoint = {local_ip}:{port}\n"
        "AllowedIPs = 0.0.0.0/0\n"
    )

    mode_spec = f"wireguard:{conf_path}"
    return client_config, mode_spec


def display_wireguard_config(config_text: str) -> None:
    """Display the WireGuard client config, with an optional QR code."""
    console.print("\n[bold]WireGuard client configuration:[/bold]\n")
    console.print(config_text)

    try:
        import segno

        qr = segno.make(config_text)
        console.print("[bold]Scan this QR code with the WireGuard app:[/bold]\n")
        qr.terminal(compact=True)  # pyright: ignore[reportUnknownMemberType]
    except ImportError:
        console.print(
            "[dim]Install segno (`uv add segno`) to display a scannable QR code.[/dim]"
        )
