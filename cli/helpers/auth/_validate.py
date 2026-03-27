"""LLM-driven script generation with interactive fix loop."""

from __future__ import annotations

from collections.abc import Callable

from cli.helpers.auth._errors import AuthScriptError, AuthScriptInvalid
from cli.helpers.auth._runtime import call_auth_module_source
from cli.helpers.console import console
from cli.helpers.llm import Conversation
from cli.helpers.prompt import render

MAX_FIX_ATTEMPTS = 10


def validate_function(
    conv: Conversation,
    extract_fn: Callable[[str], str | None],
    script: str | None = None,
    *,
    initial_text: str | None = None,
    fn: str,
    fn_args: tuple[object, ...] = (),
) -> tuple[str, object] | None:
    """Extract, run, and fix *fn* in a single loop.

    Either *script* (already extracted) or *initial_text* (raw LLM output
    to extract from) must be provided.  Returns ``(script, result)`` on
    success, or ``None`` if all attempts were exhausted or NO_AUTH.

    *extract_fn* is the callable used to parse a script from LLM output
    (e.g. ``extract_script`` or ``extract_refresh_script``).
    """

    prompt_cache: dict[str, str] = {}
    # Text waiting to be extracted — set on first iteration or after a fix
    pending_text = initial_text

    for attempt in range(MAX_FIX_ATTEMPTS):
        # ── Extract script from LLM text if needed ──────────────────
        if pending_text is not None:
            try:
                script = extract_fn(pending_text)
            except AuthScriptInvalid as e:
                console.print(
                    f"[yellow]Invalid script (attempt {attempt + 1}/{MAX_FIX_ATTEMPTS}):[/yellow] {e}"
                )
                console.print("[dim]Asking the LLM to fix...[/dim]")
                pending_text = conv.ask_text(
                    render("auth-fix.j2", exception=e, script_stdout="")
                )
                continue
            pending_text = None

            if script is None:
                console.print(
                    "[dim]No authentication mechanism detected in traces. "
                    "No script generated.[/dim]"
                )
                return None

            console.print(f"[bold]Script generated. Testing {fn}()...[/bold]")

        assert script is not None

        # ── Test the script ─────────────────────────────────────────
        output: list[str] = []
        try:
            fn_result = call_auth_module_source(
                script, fn, output, *fn_args, prompt_cache=prompt_cache
            )
            console.print(f"[green]{fn}() succeeded.[/green]")
            return script, fn_result
        except AuthScriptError as e:
            cause = e.__cause__ or e
            console.print(
                f"[yellow]{fn}() failed (attempt {attempt + 1}/{MAX_FIX_ATTEMPTS}):[/yellow] "
                f"{cause}"
            )
            console.print("[dim]Asking the LLM to fix the script...[/dim]")

        pending_text = conv.ask_text(
            render(
                "auth-fix.j2",
                exception=cause,
                script_stdout="".join(output),
            )
        )

    console.print(
        f"[red]Exhausted {MAX_FIX_ATTEMPTS} fix attempts for {fn}(). "
        f"The LLM was unable to produce a working script.[/red]"
    )
    return None
