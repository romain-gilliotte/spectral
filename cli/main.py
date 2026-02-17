"""CLI entry point for spectral."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="spectral")
def cli():
    """Automatically discover and document web application APIs."""


@cli.command()
@click.argument("capture_path", type=click.Path(exists=True))
@click.option("-o", "--output", required=True, help="Output file path for the API spec (.json)")
@click.option("--model", default="claude-sonnet-4-5-20250929", help="LLM model to use")
@click.option("--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/")
@click.option("--skip-enrich", is_flag=True, default=False, help="Skip LLM enrichment step (business context, glossary, etc.)")
def analyze(capture_path: str, output: str, model: str, debug: bool, skip_enrich: bool):
    """Analyze a capture bundle and produce an enriched API spec."""
    import anthropic

    from cli.analyze.pipeline import build_spec
    from cli.capture.loader import load_bundle

    console.print(f"[bold]Loading capture bundle:[/bold] {capture_path}")
    bundle = load_bundle(capture_path)
    console.print(
        f"  Loaded {len(bundle.traces)} traces, "
        f"{len(bundle.ws_connections)} WS connections, "
        f"{len(bundle.contexts)} contexts"
    )

    client = anthropic.AsyncAnthropic(max_retries=3)

    def on_progress(msg):
        console.print(f"  {msg}")

    console.print(f"[bold]Analyzing with LLM ({model})...[/bold]")
    spec = asyncio.run(
        build_spec(
            bundle,
            client=client,
            model=model,
            source_filename=Path(capture_path).name,
            on_progress=on_progress,
            enable_debug=debug,
            skip_enrich=skip_enrich,
        )
    )
    console.print(
        f"  Found {len(spec.protocols.rest.endpoints)} endpoints"
    )

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(spec.model_dump_json(indent=2, by_alias=True))
    console.print(f"[green]API spec written to {output}[/green]")


@cli.command()
@click.argument("spec_path", type=click.Path(exists=True))
@click.option(
    "--type",
    "output_type",
    required=True,
    type=click.Choice(["openapi", "mcp-server", "python-client", "markdown-docs", "curl-scripts"]),
    help="Output type to generate",
)
@click.option("-o", "--output", required=True, help="Output path (file or directory)")
def generate(spec_path: str, output_type: str, output: str):
    """Generate outputs from an enriched API spec."""
    from cli.formats.api_spec import ApiSpec

    console.print(f"[bold]Loading API spec:[/bold] {spec_path}")
    spec = ApiSpec.model_validate_json(Path(spec_path).read_text())

    generators = {
        "openapi": _generate_openapi,
        "mcp-server": _generate_mcp_server,
        "python-client": _generate_python_client,
        "markdown-docs": _generate_markdown_docs,
        "curl-scripts": _generate_curl_scripts,
    }

    gen_func = generators[output_type]
    gen_func(spec, output)
    console.print(f"[green]Generated {output_type} at {output}[/green]")


def _generate_openapi(spec, output):
    from cli.generate.openapi import generate_openapi
    generate_openapi(spec, output)


def _generate_mcp_server(spec, output):
    from cli.generate.mcp_server import generate_mcp_server
    generate_mcp_server(spec, output)


def _generate_python_client(spec, output):
    from cli.generate.python_client import generate_python_client
    generate_python_client(spec, output)


def _generate_markdown_docs(spec, output):
    from cli.generate.markdown_docs import generate_markdown_docs
    generate_markdown_docs(spec, output)


def _generate_curl_scripts(spec, output):
    from cli.generate.curl_scripts import generate_curl_scripts
    generate_curl_scripts(spec, output)


@cli.command()
@click.argument("capture_path", type=click.Path(exists=True))
@click.option(
    "--types",
    required=True,
    help="Comma-separated output types: openapi,mcp-server,python-client,markdown-docs,curl-scripts",
)
@click.option("-o", "--output", required=True, help="Output directory")
@click.option("--model", default="claude-sonnet-4-5-20250929", help="LLM model to use")
@click.option("--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/")
@click.option("--skip-enrich", is_flag=True, default=False, help="Skip LLM enrichment step (business context, glossary, etc.)")
def pipeline(capture_path: str, types: str, output: str, model: str, debug: bool, skip_enrich: bool):
    """Run the full pipeline: analyze + generate."""
    import anthropic

    from cli.analyze.pipeline import build_spec
    from cli.capture.loader import load_bundle

    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Analyze
    console.print(f"[bold]Loading capture bundle:[/bold] {capture_path}")
    bundle = load_bundle(capture_path)

    client = anthropic.AsyncAnthropic(max_retries=3)

    def on_progress(msg):
        console.print(f"  {msg}")

    console.print(f"[bold]Analyzing with LLM ({model})...[/bold]")
    spec = asyncio.run(
        build_spec(
            bundle,
            client=client,
            model=model,
            source_filename=Path(capture_path).name,
            on_progress=on_progress,
            enable_debug=debug,
            skip_enrich=skip_enrich,
        )
    )

    # Save intermediate spec
    spec_path = output_dir / "api_spec.json"
    spec_path.write_text(spec.model_dump_json(indent=2, by_alias=True))
    console.print(f"[green]API spec written to {spec_path}[/green]")

    # Generate outputs
    type_list = [t.strip() for t in types.split(",")]
    gen_map = {
        "openapi": ("openapi.yaml", _generate_openapi),
        "mcp-server": ("mcp-server/", _generate_mcp_server),
        "python-client": ("client.py", _generate_python_client),
        "markdown-docs": ("docs/", _generate_markdown_docs),
        "curl-scripts": ("scripts/", _generate_curl_scripts),
    }

    for t in type_list:
        t = t.strip()
        if t not in gen_map:
            console.print(f"[red]Unknown type: {t}[/red]")
            continue
        filename, gen_func = gen_map[t]
        out_path = output_dir / filename
        gen_func(spec, str(out_path))
        console.print(f"[green]Generated {t} at {out_path}[/green]")


@cli.command("call")
@click.argument("spec_path", type=click.Path(exists=True))
@click.argument("args", nargs=-1)
@click.option("--list", "list_endpoints", is_flag=True, default=False, help="List available endpoints")
@click.option("--token", default=None, help="Auth token")
@click.option("--username", default=None, help="Username for login")
@click.option("--password", default=None, help="Password for login")
@click.option("--base-url", default=None, help="Override base URL")
def call_command(spec_path: str, args: tuple, list_endpoints: bool, token: str | None, username: str | None, password: str | None, base_url: str | None):
    """Call an API endpoint from an enriched spec.

    \b
    Examples:
      spectral call spec.json --list
      spectral call spec.json get_users
      spectral call spec.json get_user user_id=123 --token eyJ...
      spectral call spec.json login --username user@x.com --password secret
    """
    from cli.client import ApiClient

    try:
        client = ApiClient(
            spec_path,
            base_url=base_url,
            token=token,
            username=username,
            password=password,
        )
    except Exception as e:
        console.print(f"[red]Error initializing client: {e}[/red]")
        sys.exit(1)

    if list_endpoints or not args:
        endpoints = client.endpoints()
        table = Table(title="Available Endpoints")
        table.add_column("ID", style="cyan")
        table.add_column("Method")
        table.add_column("Path")
        table.add_column("Purpose")
        for ep in endpoints:
            table.add_row(ep["id"], ep["method"], ep["path"], ep["purpose"])
        console.print(table)
        return

    endpoint_id = args[0]
    kwargs = {}
    for arg in args[1:]:
        if "=" in arg:
            key, value = arg.split("=", 1)
            kwargs[key] = value
        else:
            console.print(f"[red]Invalid parameter format: {arg} (expected key=value)[/red]")
            sys.exit(1)

    try:
        result = client.call(endpoint_id, **kwargs)
        if result is not None:
            console.print_json(json.dumps(result, default=str))
        else:
            console.print("[dim]No content[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.group()
def android():
    """Android APK capture tools (pull, patch, MITM proxy)."""


@android.command("list")
@click.argument("filter", default=None, required=False)
def list_cmd(filter: str | None):
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
def pull(package: str, output: str | None):
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
def patch(apk_path: str, output: str | None):
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
def install(apk_path: str):
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
def capture(port: int, output: str | None, domains: tuple[str, ...]):
    """Capture traffic from an Android app via MITM proxy.

    Without -d, runs in discovery mode: logs domains without MITM.
    With -d, captures matching traffic and writes a bundle.
    """
    from cli.android.proxy import run_proxy

    allow_hosts = list(domains) if domains else None
    discovery_mode = not allow_hosts

    if discovery_mode:
        console.print(f"[bold]Starting domain discovery on port {port}[/bold]")
        console.print(f"  No -d specified — passthrough mode, logging domains only.")
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


@cli.command()
@click.argument("capture_path", type=click.Path(exists=True))
@click.option("--trace", "trace_id", default=None, help="Show details for a specific trace")
def inspect(capture_path: str, trace_id: str | None):
    """Inspect a capture bundle."""
    from cli.capture.loader import load_bundle

    bundle = load_bundle(capture_path)

    if trace_id:
        _inspect_trace(bundle, trace_id)
    else:
        _inspect_summary(bundle)


def _inspect_summary(bundle):
    """Print a summary of the capture bundle."""
    m = bundle.manifest
    console.print(f"[bold]Capture Bundle Summary[/bold]")
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


def _inspect_trace(bundle, trace_id: str):
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


def _print_body(body: bytes):
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



def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


if __name__ == "__main__":
    cli()
