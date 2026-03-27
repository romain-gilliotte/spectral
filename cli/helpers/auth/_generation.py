import re

from cli.helpers.auth._errors import AuthScriptInvalid
from cli.helpers.prompt import render

_NO_AUTH_SENTINEL = "NO_AUTH"


def get_auth_rules() -> str:
    """Return the shared auth script rules (for system prompt)."""
    return render("auth-rules.j2", no_auth_sentinel=_NO_AUTH_SENTINEL)


def get_acquire_instructions() -> str:
    """Return the acquire_token task prompt (for user message)."""
    return render("auth-acquire.j2", no_auth_sentinel=_NO_AUTH_SENTINEL)


def get_refresh_instructions() -> str:
    """Return the refresh_token task prompt (for user message)."""
    return render("auth-refresh.j2", no_auth_sentinel=_NO_AUTH_SENTINEL)


def extract_script(text: str) -> str | None:
    """Extract and validate a Python auth script defining ``acquire_token``."""
    return _extract_and_validate(text, "acquire_token", "<auth-acquire>")


def extract_refresh_script(text: str) -> str | None:
    """Extract and validate a Python auth script defining ``refresh_token``."""
    return _extract_and_validate(text, "refresh_token", "<auth-refresh>")


# ── Internal helpers ──────────────────────────────────────────────────────


def _extract_and_validate(text: str, fn_name: str, filename: str) -> str | None:
    """Extract a script from LLM output and check it defines *fn_name*.

    Returns ``None`` if the LLM signalled NO_AUTH.
    Raises ``AuthScriptInvalid`` if the script is invalid or missing *fn_name*.
    """
    script = _extract_code_block(text)
    if script is None:
        return None

    ns = _compile_and_exec(script, filename)

    if not callable(ns.get(fn_name)):
        article = "an" if fn_name[0] in "aeiou" else "a"
        raise AuthScriptInvalid(
            f"Generated script must define {article} {fn_name}() function"
        )

    return script


def _extract_code_block(text: str) -> str | None:
    """Extract a Python code block from LLM output.

    Returns ``None`` if the LLM signalled NO_AUTH.
    Raises ``AuthScriptInvalid`` on syntax/import errors.
    """
    if _NO_AUTH_SENTINEL in text and "```" not in text:
        return None

    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() + "\n" if match else text.strip() + "\n"


def _compile_and_exec(script: str, filename: str) -> dict[str, object]:
    """Compile and exec a script, returning the resulting namespace."""
    try:
        code = compile(script, filename, "exec")
    except SyntaxError as e:
        raise AuthScriptInvalid(f"Generated script has syntax error: {e}") from e

    ns: dict[str, object] = {}
    try:
        exec(code, ns)
    except Exception as e:
        raise AuthScriptInvalid(f"Generated script fails at import time: {e}") from e

    return ns
