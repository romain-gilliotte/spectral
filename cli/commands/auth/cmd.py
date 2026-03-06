"""CLI command for auth analysis, login, logout, and refresh."""

from __future__ import annotations

import asyncio

import click

from cli.helpers.console import console


@click.group()
def auth() -> None:
    """Authentication analysis and management."""


@auth.command()
@click.argument("app_name")
@click.option("--model", default="claude-sonnet-4-5-20250929", help="LLM model to use")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def analyze(app_name: str, model: str, debug: bool) -> None:
    """Analyze auth mechanism for an app and generate an auth script."""
    from datetime import datetime, timezone
    from pathlib import Path

    import cli.helpers.llm as llm
    from cli.helpers.storage import auth_script_path, load_app_bundle, resolve_app

    resolve_app(app_name)
    console.print(f"[bold]Loading captures for app:[/bold] {app_name}")
    bundle = load_app_bundle(app_name)
    console.print(f"  Loaded {len(bundle.traces)} traces")

    debug_dir = None
    if debug:
        run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        debug_dir = Path("debug") / run_ts
        debug_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"  Debug logs → {debug_dir}")

    llm.init(debug_dir=debug_dir, model=model)

    from cli.commands.auth.analyze import NoAuthDetected, generate_auth_script
    from cli.helpers.context import build_shared_context
    from cli.helpers.detect_base_url import detect_base_url
    from cli.helpers.storage import update_app_meta

    async def _run() -> str:
        base_url = await detect_base_url(bundle, app_name)
        console.print(f"  API base URL: {base_url}")

        system_context = build_shared_context(bundle, base_url)

        script = await generate_auth_script(
            traces=bundle.traces,
            api_name=app_name,
            system_context=system_context,
        )

        update_app_meta(app_name, base_url=base_url)

        return script

    try:
        script = asyncio.run(_run())
    except NoAuthDetected:
        console.print()
        console.print(
            "[dim]No authentication mechanism detected in traces. "
            "No script generated.[/dim]"
        )
        _print_usage(model)
        return

    script_path = auth_script_path(app_name)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script)
    console.print(f"[green]Auth script written to {script_path}[/green]")

    _print_usage(model)


@auth.command("set")
@click.argument("app_name")
@click.option("--header", "-H", multiple=True, help='Header as "Name: Value" (repeatable)')
@click.option("--cookie", "-c", multiple=True, help='Cookie as "name=value" (repeatable)')
def set_token(app_name: str, header: tuple[str, ...], cookie: tuple[str, ...]) -> None:
    """Manually set auth headers/cookies for an app.

    Fallback when the generated auth script doesn't work.
    """
    import time

    from cli.formats.mcp_tool import TokenState
    from cli.helpers.storage import resolve_app, write_token

    resolve_app(app_name)

    headers: dict[str, str] = {}

    for h in header:
        if ": " not in h:
            raise click.ClickException(
                f"Invalid header format: {h!r}. Expected 'Name: Value'."
            )
        name, value = h.split(": ", 1)
        headers[name] = value

    if cookie:
        headers["Cookie"] = "; ".join(cookie)

    if not headers:
        token = click.prompt("Token")
        if token.startswith("Bearer "):
            token = token[len("Bearer "):]
        headers["Authorization"] = f"Bearer {token}"

    token_state = TokenState(headers=headers, obtained_at=time.time())
    write_token(app_name, token_state)
    console.print("[green]Token saved.[/green]")


@auth.command()
@click.argument("app_name")
def login(app_name: str) -> None:
    """Run interactive authentication for an app.

    Loads auth_acquire.py, calls acquire_token(), and writes token.json.
    """
    from cli.commands.mcp.auth import acquire_auth
    from cli.helpers.storage import resolve_app, write_token

    resolve_app(app_name)

    console.print(f"[bold]Logging in to {app_name}...[/bold]")
    token = acquire_auth(app_name)
    write_token(app_name, token)
    console.print("[green]Login successful. Token saved.[/green]")


@auth.command()
@click.argument("app_name")
def logout(app_name: str) -> None:
    """Remove stored token for an app."""
    from cli.helpers.storage import delete_token, resolve_app

    resolve_app(app_name)

    if delete_token(app_name):
        console.print(f"[green]Logged out of {app_name}. Token removed.[/green]")
    else:
        console.print(f"[dim]No token found for '{app_name}'. Nothing to remove.[/dim]")


@auth.command()
@click.argument("app_name")
def refresh(app_name: str) -> None:
    """Manually refresh the auth token for an app.

    Loads token.json, calls refresh_token(), and updates token.json.
    """
    from cli.commands.mcp.auth import AuthError, refresh_auth
    from cli.helpers.storage import load_token, resolve_app, write_token

    resolve_app(app_name)

    token = load_token(app_name)
    if token is None:
        raise click.ClickException(
            f"No token found for '{app_name}'. Run 'spectral auth login {app_name}' first."
        )

    try:
        new_token = refresh_auth(app_name, token)
    except AuthError as exc:
        raise click.ClickException(str(exc)) from exc

    write_token(app_name, new_token)
    console.print("[green]Token refreshed successfully.[/green]")


def _print_usage(model: str) -> None:
    import cli.helpers.llm as llm

    inp_tok, out_tok = llm.get_usage()
    if inp_tok or out_tok:
        cache_read, cache_create = llm.get_cache_usage()
        cost = llm.estimate_cost(model, inp_tok, out_tok, cache_read, cache_create)
        cost_str = f" (~${cost:.2f})" if cost is not None else ""
        console.print(f"  LLM token usage: {inp_tok:,} input, {out_tok:,} output{cost_str}")
