"""CLI entry point for api-discover."""

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
@click.version_option(version="0.1.0", prog_name="api-discover")
def cli():
    """Automatically discover and document web application APIs."""


@cli.command()
@click.argument("capture_path", type=click.Path(exists=True))
@click.option("-o", "--output", required=True, help="Output file path for the API spec (.json)")
@click.option("--model", default="claude-sonnet-4-5-20250929", help="LLM model to use")
def analyze(capture_path: str, output: str, model: str):
    """Analyze a capture bundle and produce an enriched API spec."""
    import anthropic

    from cli.analyze.spec_builder import build_spec
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
def pipeline(capture_path: str, types: str, output: str, model: str):
    """Run the full pipeline: analyze + generate."""
    import anthropic

    from cli.analyze.spec_builder import build_spec
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
    console.print(f"  Browser: {m.browser.name} {m.browser.version}")
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
