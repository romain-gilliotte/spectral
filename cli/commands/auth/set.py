"""CLI command: spectral auth set."""

from __future__ import annotations

import click

from cli.helpers.console import console


@click.command("set")
@click.argument("app_name")
@click.option("--header", "-H", multiple=True, help='Header as "Name: Value" (repeatable)')
@click.option("--cookie", "-c", multiple=True, help='Cookie as "name=value" (repeatable)')
@click.option(
    "--body-param",
    "-b",
    multiple=True,
    help='Body param as "key=value" (repeatable)',
)
def set_token(
    app_name: str,
    header: tuple[str, ...],
    cookie: tuple[str, ...],
    body_param: tuple[str, ...],
) -> None:
    """Manually set auth headers/cookies/body params for an app.

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

    body_params: dict[str, str] = {}
    for bp in body_param:
        if "=" not in bp:
            raise click.ClickException(
                f"Invalid body param format: {bp!r}. Expected 'key=value'."
            )
        key, value = bp.split("=", 1)
        body_params[key] = value

    if not headers and not body_params:
        token = click.prompt("Token")
        if token.startswith("Bearer "):
            token = token[len("Bearer "):]
        headers["Authorization"] = f"Bearer {token}"

    token_state = TokenState(
        headers=headers, body_params=body_params, obtained_at=time.time()
    )
    write_token(app_name, token_state)
    console.print("[green]Token saved.[/green]")
