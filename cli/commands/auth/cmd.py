"""CLI command for auth analysis, login, logout, and refresh."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import click

from cli.helpers.console import console

if TYPE_CHECKING:
    from cli.commands.capture.types import CaptureBundle
    from cli.helpers.llm import Conversation


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
    import cli.helpers.llm as llm
    from cli.helpers.storage import auth_script_path, load_app_bundle, resolve_app

    resolve_app(app_name)
    console.print(f"[bold]Loading captures for app:[/bold] {app_name}")
    bundle = load_app_bundle(app_name)
    console.print(f"  Loaded {len(bundle.traces)} traces")

    llm.init_debug(debug=debug)
    llm.set_model(model)

    from cli.commands.auth.analyze import NoAuthDetected, generate_auth_script
    from cli.helpers.context import build_shared_context
    from cli.helpers.detect_base_url import detect_base_url
    from cli.helpers.storage import update_app_meta

    async def _run() -> str:
        base_url = await detect_base_url(bundle, app_name)
        console.print(f"  API base URL: {base_url}")

        system_context = build_shared_context(bundle, base_url)

        script = await generate_auth_script(
            bundle=bundle,
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
        return

    script_path = auth_script_path(app_name)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script)
    console.print(f"[green]Auth script written to {script_path}[/green]")


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
@click.option("--model", default="claude-sonnet-4-5-20250929", help="LLM model to use")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def login(app_name: str, model: str, debug: bool) -> None:
    """Run interactive authentication for an app.

    Loads auth_acquire.py, calls acquire_token(), and writes token.json.
    If the script fails, offers to fix it with the LLM.
    """
    import traceback

    from cli.commands.mcp.auth import acquire_auth, captured_script_output
    from cli.helpers.storage import auth_script_path, resolve_app, write_token

    resolve_app(app_name)

    # Lazily initialized on first fix attempt
    bundle: CaptureBundle | None = None
    system_context: str | None = None
    fix_conv: Conversation | None = None  # reused across fix attempts

    while True:
        console.print(f"[bold]Logging in to {app_name}...[/bold]")
        try:
            token = acquire_auth(app_name)
        except Exception:
            traceback_str = traceback.format_exc()
            stdout_output = "".join(captured_script_output)
            if stdout_output:
                traceback_str = f"## Script stdout\n\n{stdout_output}\n## Traceback\n\n{traceback_str}"
            console.print("[red]Login failed:[/red]")
            console.print(traceback_str)

            if not click.confirm(
                "Would you like the LLM to fix the auth script?", default=True
            ):
                raise SystemExit(1)

            # Lazy init LLM, bundle, and system context on first fix
            if bundle is None:
                from cli.helpers.context import build_shared_context
                from cli.helpers.detect_base_url import detect_base_url
                import cli.helpers.llm as llm_mod
                from cli.helpers.storage import load_app_bundle

                llm_mod.init_debug(debug=debug)
                llm_mod.set_model(model)

                bundle = load_app_bundle(app_name)

                async def _detect_url() -> str:
                    return await detect_base_url(bundle, app_name)  # type: ignore[arg-type]

                base_url = asyncio.run(_detect_url())
                system_context = build_shared_context(bundle, base_url)

            from cli.commands.auth.analyze import fix_auth_script

            script_path = auth_script_path(app_name)
            current_script = script_path.read_text()

            fixed_script, fix_conv = asyncio.run(
                fix_auth_script(
                    bundle=bundle,
                    api_name=app_name,
                    system_context=system_context,
                    current_script=current_script,
                    error_trace=traceback_str,
                    conv=fix_conv,
                )
            )

            script_path.write_text(fixed_script)
            console.print("[green]Script updated. Retrying login...[/green]")
            continue

        write_token(app_name, token)
        console.print("[green]Login successful. Token saved.[/green]")
        break


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
@click.option("--model", default="claude-sonnet-4-5-20250929", help="LLM model to use")
@click.option(
    "--debug", is_flag=True, default=False, help="Save LLM prompts/responses to debug/"
)
def extract(app_name: str, model: str, debug: bool) -> None:
    """Extract auth tokens from captured traces.

    Scans the most recent traces for auth headers (Authorization, cookies, etc.)
    and writes them to token.json without re-authentication.
    """
    from cli.commands.auth.extract import extract_auth_from_traces
    import cli.helpers.llm as llm
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
