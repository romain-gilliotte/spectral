"""Auth cascade: generation, runtime execution, and token management."""

from cli.helpers.auth._errors import (
    AuthError,
    AuthScriptError,
    AuthScriptInvalid,
    AuthScriptNotFound,
)
from cli.helpers.auth._generation import (
    extract_script,
    get_auth_instructions,
    script_has_refresh,
)
from cli.helpers.auth._runtime import call_auth_module, call_auth_module_source
from cli.helpers.auth._usage import (
    acquire_auth,
    get_auth,
    refresh_auth,
    save_auth_result,
)

__all__ = [
    "AuthError",
    "AuthScriptError",
    "AuthScriptInvalid",
    "AuthScriptNotFound",
    "acquire_auth",
    "call_auth_module",
    "call_auth_module_source",
    "extract_script",
    "get_auth",
    "get_auth_instructions",
    "refresh_auth",
    "save_auth_result",
    "script_has_refresh",
]
