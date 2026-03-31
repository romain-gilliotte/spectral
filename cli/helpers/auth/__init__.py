"""Auth cascade: generation, runtime execution, and token management."""

from cli.helpers.auth._errors import (
    AuthError,
    AuthScriptError,
    AuthScriptInvalid,
    AuthScriptNotFound,
)
from cli.helpers.auth._extract import (
    extract_headers_by_name,
    extract_refresh_token,
    filter_traces_by_base_url,
    find_authorization_header,
)
from cli.helpers.auth._generation import (
    extract_refresh_script,
    extract_script,
    get_acquire_instructions,
    get_auth_rules,
    get_refresh_instructions,
)
from cli.helpers.auth._runtime import call_auth_module, call_auth_module_source
from cli.helpers.auth._usage import (
    acquire_auth,
    get_auth,
    refresh_auth,
    save_auth_result,
)
from cli.helpers.auth._validate import validate_function

__all__ = [
    "AuthError",
    "AuthScriptError",
    "AuthScriptInvalid",
    "AuthScriptNotFound",
    "acquire_auth",
    "call_auth_module",
    "call_auth_module_source",
    "extract_headers_by_name",
    "extract_refresh_token",
    "filter_traces_by_base_url",
    "find_authorization_header",
    "extract_refresh_script",
    "extract_script",
    "get_auth",
    "get_acquire_instructions",
    "get_auth_rules",
    "get_refresh_instructions",
    "refresh_auth",
    "save_auth_result",
    "validate_function",
]
