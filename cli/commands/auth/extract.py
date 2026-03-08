"""Extract auth tokens from captured traces.

Also contains the ``spectral auth extract`` Click command.
"""

from __future__ import annotations

import asyncio
import time

import click
from pydantic import BaseModel

from cli.commands.capture.types import CaptureBundle, Trace
from cli.formats.mcp_tool import TokenState
from cli.helpers.console import console
from cli.helpers.http import get_header
import cli.helpers.llm as llm
from cli.helpers.prompt import load


class AuthHeaderNamesResponse(BaseModel):
    header_names: list[str]


def _filter_traces_by_base_url(traces: list[Trace], base_url: str) -> list[Trace]:
    """Return traces whose URL starts with base_url, sorted by timestamp descending."""
    matching = [t for t in traces if t.meta.request.url.startswith(base_url)]
    matching.sort(key=lambda t: t.meta.timestamp, reverse=True)
    return matching


def _find_authorization_header(
    traces: list[Trace], base_url: str
) -> dict[str, str] | None:
    """Fast path: find Authorization header from the most recent matching trace."""
    filtered = _filter_traces_by_base_url(traces, base_url)
    for trace in filtered:
        value = get_header(trace.meta.request.headers, "Authorization")
        if value:
            return {"Authorization": value}
    return None


async def _llm_identify_auth_headers(
    bundle: CaptureBundle, base_url: str
) -> list[str]:
    """LLM fallback: ask the LLM which request header names carry authentication."""
    filtered_bundle = bundle.filter_traces(
        lambda t: t.meta.request.url.startswith(base_url)
    )

    conv = llm.Conversation(
        label="extract_auth_headers",
        tool_names=["query_traces"],
        bundle=filtered_bundle,
        max_iterations=3,
    )

    prompt = load("auth-extract-headers.j2")

    result = await conv.ask_json(prompt, AuthHeaderNamesResponse)
    return result.header_names


def _extract_headers_by_name(
    traces: list[Trace], base_url: str, names: list[str]
) -> dict[str, str] | None:
    """Given header names, find the most recent trace with those headers and return values."""
    filtered = _filter_traces_by_base_url(traces, base_url)
    names_lower = [n.lower() for n in names]

    for trace in filtered:
        headers: dict[str, str] = {}
        for h in trace.meta.request.headers:
            if h.name.lower() in names_lower:
                headers[h.name] = h.value
        if headers:
            return headers
    return None


async def extract_auth_from_traces(
    bundle: CaptureBundle, app_name: str
) -> TokenState | None:
    """Extract auth headers from the most recent traces.

    Returns a TokenState if auth headers are found, None otherwise.
    """
    from cli.helpers.detect_base_url import detect_base_url

    base_url = await detect_base_url(bundle, app_name)

    filtered = _filter_traces_by_base_url(bundle.traces, base_url)
    if not filtered:
        return None

    # Fast path: look for Authorization header
    auth_headers = _find_authorization_header(bundle.traces, base_url)
    if auth_headers:
        return TokenState(headers=auth_headers, obtained_at=time.time())

    # LLM fallback: ask which headers carry auth
    header_names = await _llm_identify_auth_headers(bundle, base_url)
    if not header_names:
        return None

    extracted = _extract_headers_by_name(bundle.traces, base_url, header_names)
    if not extracted:
        return None

    return TokenState(headers=extracted, obtained_at=time.time())


@click.command()
@click.argument("app_name")
@click.option("--model", default="claude-sonnet-4-5-20250929", help="LLM model to use")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def extract(app_name: str, model: str, debug: bool) -> None:
    """Extract auth tokens from captured traces.

    Scans the most recent traces for auth headers (Authorization, cookies, etc.)
    and writes them to token.json without re-authentication.
    """
    from cli.helpers.storage import load_app_bundle, resolve_app, write_token

    resolve_app(app_name)
    console.print(f"[bold]Loading captures for app:[/bold] {app_name}")
    bundle = load_app_bundle(app_name)
    console.print(f"  Loaded {len(bundle.traces)} traces")

    llm.init_debug(debug=debug)
    llm.set_model(model)

    token = asyncio.run(extract_auth_from_traces(bundle, app_name))

    if token is None:
        console.print(
            "[yellow]No auth headers found in traces. "
            "No token written.[/yellow]"
        )
        return

    write_token(app_name, token)
    header_names = ", ".join(token.headers.keys())
    console.print(f"[green]Token saved with headers: {header_names}[/green]")
