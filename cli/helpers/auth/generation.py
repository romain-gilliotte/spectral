import re

from cli.helpers.auth.errors import AuthScriptInvalid
from cli.helpers.prompt import render

_NO_AUTH_SENTINEL = "NO_AUTH"


def get_auth_instructions() -> str:
    """Return the rendered auth system prompt."""
    return render("auth-instructions.j2", no_auth_sentinel=_NO_AUTH_SENTINEL)


def extract_script(text: str) -> str | None:
    """Extract and validate a Python auth script from LLM output.

    Returns None if the LLM found no auth mechanism.
    Raises AuthScriptInvalid if extraction or validation fails.
    """
    if _NO_AUTH_SENTINEL in text and "```" not in text:
        return None

    # Strip markdown fences if present
    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    script = match.group(1).strip() + "\n" if match else text.strip() + "\n"

    # Compile and exec to check exports
    try:
        code = compile(script, "<auth-acquire>", "exec")
    except SyntaxError as e:
        raise AuthScriptInvalid(f"Generated script has syntax error: {e}") from e

    ns: dict[str, object] = {}
    try:
        exec(code, ns)
    except Exception as e:
        raise AuthScriptInvalid(f"Generated script fails at import time: {e}") from e

    if not callable(ns.get("acquire_token")):
        raise AuthScriptInvalid("Generated script must define an acquire_token() function")

    return script
