"""CLI commands for Android APK capture tools."""

from __future__ import annotations

from pathlib import Path

import click

from cli.console import console


@click.group()
def android() -> None:
    """Android APK capture tools (pull, patch, MITM proxy)."""


@android.command("list")
@click.argument("filter", default=None, required=False)
def list_cmd(filter: str | None) -> None:
    """List installed packages on the connected device.

    Optionally filter by a substring, e.g.: spectral android list spotify
    """
    from cli.android.adb import check_adb, list_packages

    check_adb()
    packages = list_packages(filter)

    if not packages:
        console.print("[yellow]No packages found.[/yellow]")
        return

    console.print(f"[bold]{len(packages)} packages:[/bold]")
    for pkg in packages:
        console.print(f"  {pkg}")


@android.command()
@click.argument("package")
@click.option("-o", "--output", default=None, help="Output path (file for single APK, directory for splits)")
def pull(package: str, output: str | None) -> None:
    """Pull all APKs for a package from a connected Android device.

    Single APK apps are saved as a file. Split APK apps (App Bundles)
    are saved as a directory containing all split APKs.
    """
    from cli.android.adb import check_adb, get_apk_paths, pull_apks

    check_adb()

    console.print(f"[bold]Looking up package:[/bold] {package}")
    apk_paths = get_apk_paths(package)
    is_split = len(apk_paths) > 1

    if is_split:
        console.print(f"  Found {len(apk_paths)} split APKs")
        default_output = Path(package)
    else:
        console.print("  Found single APK")
        default_output = Path(f"{package}.apk")

    out = Path(output) if output else default_output

    for p in apk_paths:
        console.print(f"  Pulling {p}")

    result_path, was_split = pull_apks(package, out)

    if was_split:
        apk_files = sorted(result_path.glob("*.apk"))
        console.print(f"[green]Split APKs saved to {result_path}/[/green]")
        for f in apk_files:
            console.print(f"  {f.name}")
    else:
        console.print(f"[green]APK saved to {result_path}[/green]")


@android.command()
@click.argument("apk_path", type=click.Path(exists=True))
@click.option("-o", "--output", default=None, help="Output path (file for single APK, directory for splits)")
def patch(apk_path: str, output: str | None) -> None:
    """Patch an APK or directory of split APKs to trust user CA certificates for MITM."""
    from cli.android.patch import patch_apk, patch_apk_dir

    apk = Path(apk_path)

    if apk.is_dir():
        out = Path(output) if output else Path(str(apk).rstrip("/") + "-patched")
        apk_count = len(list(apk.glob("*.apk")))
        console.print(f"[bold]Patching split APKs:[/bold] {apk} ({apk_count} files)")
        patch_apk_dir(apk, out)
        console.print(f"[green]Patched split APKs saved to {out}/[/green]")
        for f in sorted(out.glob("*.apk")):
            console.print(f"  {f.name}")
    else:
        out = Path(output) if output else apk.with_stem(apk.stem + "-patched")
        console.print(f"[bold]Patching APK:[/bold] {apk}")
        patch_apk(apk, out)
        console.print(f"[green]Patched APK saved to {out}[/green]")

    console.print()
    console.print("[bold]Next steps:[/bold]")
    console.print(f"  1. Install: spectral android install {out}")
    console.print("  2. Install mitmproxy CA cert on the device:")
    console.print("     - Start proxy: spectral android capture")
    console.print("     - On device, visit http://mitm.it and install the cert")
    console.print("  3. Configure device WiFi proxy to point to this machine")


@android.command()
@click.argument("apk_path", type=click.Path(exists=True))
def install(apk_path: str) -> None:
    """Install an APK or directory of split APKs to the device."""
    from cli.android.adb import check_adb, install_apk

    check_adb()

    path = Path(apk_path)
    if path.is_dir():
        apks = sorted(path.glob("*.apk"))
        console.print(f"[bold]Installing split APKs:[/bold] {path} ({len(apks)} files)")
    else:
        console.print(f"[bold]Installing APK:[/bold] {path}")

    install_apk(path)
    console.print("[green]Installation successful[/green]")


@android.command()
@click.option("-p", "--port", default=8080, help="Proxy listen port")
@click.option("-o", "--output", default=None, help="Output bundle path (.zip)")
@click.option("-d", "--domain", "domains", multiple=True, help="Only intercept these domains (regex). Can be repeated.")
def capture(port: int, output: str | None, domains: tuple[str, ...]) -> None:
    """Capture traffic from an Android app via MITM proxy.

    Without -d, runs in discovery mode: logs domains without MITM.
    With -d, captures matching traffic and writes a bundle.
    """
    from cli.android.proxy import run_proxy

    allow_hosts = list(domains) if domains else None
    discovery_mode = not allow_hosts

    if discovery_mode:
        console.print(f"[bold]Starting domain discovery on port {port}[/bold]")
        console.print("  No -d specified — passthrough mode, logging domains only.")
        output_path = Path(output) if output else None
        app_name = "android-app"
    else:
        output_path = Path(output or "capture.zip")
        app_name = output_path.stem if output else "android-app"
        console.print(f"[bold]Starting MITM proxy on port {port}[/bold]")
        console.print(f"  Output:  {output_path}")
        console.print(f"  Domains: {', '.join(allow_hosts)}")

    stats = run_proxy(port, output_path, app_name, allow_hosts=allow_hosts)
    if stats:
        console.print()
        console.print(f"[green]Capture bundle written to {output_path}[/green]")
        console.print(f"  {stats.trace_count} HTTP traces, {stats.ws_connection_count} WS connections, {stats.ws_message_count} WS messages")
