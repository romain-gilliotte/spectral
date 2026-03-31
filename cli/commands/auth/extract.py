"""Extract auth tokens from captured traces.

Also contains the ``spectral auth extract`` Click command.
"""

from __future__ import annotations

import time

import click
from pydantic import BaseModel

from cli.commands.capture.types import CaptureBundle
from cli.formats.mcp_tool import TokenState
from cli.helpers.auth import (
    extract_headers_by_name,
    extract_refresh_token,
    filter_traces_by_base_url,
    find_authorization_header,
)
from cli.helpers.console import console
import cli.helpers.llm as llm
from cli.helpers.prompt import load
from cli.helpers.storage import load_app_bundle, resolve_app, write_token


@click.command()
@click.argument("app_name")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def extract(app_name: str, debug: bool) -> None:
    """Extract auth tokens from captured traces.

    Scans the most recent traces for auth headers (Authorization, cookies, etc.)
    and writes them to token.json without re-authentication.
    """

    resolve_app(app_name)
    llm.init_debug(debug=debug)

    bundle = load_app_bundle(app_name)
    token = _extract_auth_from_traces(bundle, app_name)

    if token is None:
        console.print(
            "[yellow]No auth headers found in traces. No token written.[/yellow]"
        )
        return

    write_token(app_name, token)
    header_names = ", ".join(token.headers.keys())
    console.print(f"[green]Token saved with headers: {header_names}[/green]")
    if token.refresh_token:
        console.print(f"[green]Refresh token: {token.refresh_token[:20]}...[/green]")


# ── Internal helpers ──────────────────────────────────────────────────────


def _extract_auth_from_traces(
    bundle: CaptureBundle, app_name: str
) -> TokenState | None:
    """Extract auth headers and refresh token from the most recent traces."""
    from cli.helpers.detect_base_url import detect_base_urls

    base_url = detect_base_urls(bundle, app_name)[0]

    filtered = filter_traces_by_base_url(bundle.traces, base_url)
    if not filtered:
        return None

    # Fast path: look for Authorization header
    auth_headers = find_authorization_header(filtered)
    if not auth_headers:
        # LLM fallback: ask which headers carry auth
        header_names = _llm_identify_auth_headers(bundle, base_url)
        if not header_names:
            return None
        auth_headers = extract_headers_by_name(bundle.traces, base_url, header_names)
        if not auth_headers:
            return None

    # Also try to extract a refresh token from response bodies
    refresh_token = extract_refresh_token(bundle, base_url)

    return TokenState(
        headers=auth_headers,
        refresh_token=refresh_token,
        obtained_at=time.time(),
    )


class _AuthHeaderNamesResponse(BaseModel):
    header_names: list[str]


def _llm_identify_auth_headers(bundle: CaptureBundle, base_url: str) -> list[str]:
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

    result = conv.ask_json(prompt, _AuthHeaderNamesResponse)
    return result.header_names
