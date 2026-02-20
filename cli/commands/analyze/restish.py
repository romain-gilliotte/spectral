"""Generate Restish API config from analysis results.

Produces a ``.restish.json`` config entry that maps ``AuthInfo`` to Restish's
profile format (headers, auth schemes, or external-tool).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cli.commands.analyze.steps.types import AuthInfo


def generate_restish_entry(
    base_url: str,
    spec_path: Path,
    auth: AuthInfo,
    auth_helper_path: str | None = None,
) -> dict[str, Any]:
    """Build a single Restish API config entry.

    The returned dict is one entry suitable for merging into the Restish
    ``apis`` object in ``~/.config/restish/apis.json``.
    """
    entry: dict[str, Any] = {
        "base": base_url,
        "spec_files": [str(spec_path)],
    }
    profile = map_auth(auth, auth_helper_path)
    if profile:
        entry["profiles"] = {"default": profile}
    return entry


def map_auth(
    auth: AuthInfo, auth_helper_path: str | None = None
) -> dict[str, Any]:
    """Map an AuthInfo to a Restish profile dict.

    Returns an empty dict when no auth configuration is needed.
    """
    auth_type = auth.type.lower().strip() if auth.type else ""
    obtain_flow = auth.obtain_flow.lower().strip() if auth.obtain_flow else ""

    if not auth_type or auth_type == "none":
        return {}

    # api_key → static header placeholder
    if auth_type == "api_key":
        header = auth.token_header or "X-API-Key"
        return {"headers": {header: "<API_KEY>"}}

    # basic auth
    if auth_type == "basic":
        return {
            "auth": {
                "name": "http-basic",
                "params": {"username": "", "password": ""},
            }
        }

    # bearer_token with OAuth2 client credentials
    if auth_type == "bearer_token" and obtain_flow == "oauth2_client_credentials":
        login = auth.login_config
        token_url = login.url if login else ""
        client_id = ""
        if login and login.credential_fields:
            client_id = login.credential_fields.get("client_id", "")
        return {
            "auth": {
                "name": "oauth-client-credentials",
                "params": {
                    "client_id": client_id,
                    "token_url": token_url,
                    "client_secret": "",
                },
            }
        }

    # bearer_token with OAuth2 authorization code → static placeholder
    if auth_type == "bearer_token" and obtain_flow == "oauth2_authorization_code":
        return {"headers": {"Authorization": "Bearer <TOKEN>"}}

    # bearer_token or cookie with login_config → external-tool
    if auth.login_config and auth_helper_path:
        return {
            "auth": {
                "name": "external-tool",
                "params": {
                    "commandline": f"python3 {auth_helper_path}",
                },
            }
        }

    # bearer_token without login_config → static placeholder
    if auth_type == "bearer_token":
        prefix = auth.token_prefix or "Bearer"
        header = auth.token_header or "Authorization"
        return {"headers": {header: f"{prefix} <TOKEN>"}}

    # cookie without login_config → static placeholder
    if auth_type == "cookie":
        return {"headers": {"Cookie": "<SESSION>"}}

    # Fallback: no auth config
    return {}
