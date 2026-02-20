"""Tests for Restish config generation."""

from __future__ import annotations

from pathlib import Path

from cli.commands.analyze.restish import (
    generate_restish_entry,
    map_auth,
)
from cli.commands.analyze.steps.types import (
    AuthInfo,
    LoginEndpointConfig,
)


class TestMapAuth:
    """Tests for map_auth — mapping AuthInfo to Restish profile dicts."""

    def test_none_auth(self) -> None:
        auth = AuthInfo(type="none")
        assert map_auth(auth) == {}

    def test_empty_auth(self) -> None:
        auth = AuthInfo(type="")
        assert map_auth(auth) == {}

    def test_api_key(self) -> None:
        auth = AuthInfo(type="api_key", token_header="X-API-Key")
        result = map_auth(auth)
        assert result == {"headers": {"X-API-Key": "<API_KEY>"}}

    def test_api_key_default_header(self) -> None:
        auth = AuthInfo(type="api_key")
        result = map_auth(auth)
        assert result == {"headers": {"X-API-Key": "<API_KEY>"}}

    def test_basic_auth(self) -> None:
        auth = AuthInfo(type="basic")
        result = map_auth(auth)
        assert result == {
            "auth": {
                "name": "http-basic",
                "params": {"username": "", "password": ""},
            }
        }

    def test_oauth2_client_credentials(self) -> None:
        auth = AuthInfo(
            type="bearer_token",
            obtain_flow="oauth2_client_credentials",
            login_config=LoginEndpointConfig(
                url="https://auth.example.com/token",
                credential_fields={"client_id": "my-client"},
            ),
        )
        result = map_auth(auth)
        assert result == {
            "auth": {
                "name": "oauth-client-credentials",
                "params": {
                    "client_id": "my-client",
                    "token_url": "https://auth.example.com/token",
                    "client_secret": "",
                },
            }
        }

    def test_oauth2_authorization_code_placeholder(self) -> None:
        auth = AuthInfo(
            type="bearer_token",
            obtain_flow="oauth2_authorization_code",
        )
        result = map_auth(auth)
        assert result == {"headers": {"Authorization": "Bearer <TOKEN>"}}

    def test_bearer_with_login_config_external_tool(self) -> None:
        auth = AuthInfo(
            type="bearer_token",
            obtain_flow="login_form",
            login_config=LoginEndpointConfig(
                url="https://api.example.com/login",
            ),
        )
        result = map_auth(auth, auth_helper_path="/tmp/myapi-auth.py")
        assert result == {
            "auth": {
                "name": "external-tool",
                "params": {
                    "commandline": "python3 /tmp/myapi-auth.py",
                },
            }
        }

    def test_cookie_with_login_config_external_tool(self) -> None:
        auth = AuthInfo(
            type="cookie",
            obtain_flow="login_form",
            login_config=LoginEndpointConfig(
                url="https://api.example.com/login",
            ),
        )
        result = map_auth(auth, auth_helper_path="/tmp/myapi-auth.py")
        assert result == {
            "auth": {
                "name": "external-tool",
                "params": {
                    "commandline": "python3 /tmp/myapi-auth.py",
                },
            }
        }

    def test_bearer_without_login_config_placeholder(self) -> None:
        auth = AuthInfo(
            type="bearer_token",
            token_header="Authorization",
            token_prefix="Bearer",
        )
        result = map_auth(auth)
        assert result == {"headers": {"Authorization": "Bearer <TOKEN>"}}

    def test_bearer_custom_prefix(self) -> None:
        auth = AuthInfo(
            type="bearer_token",
            token_header="X-Auth-Token",
            token_prefix="Token",
        )
        result = map_auth(auth)
        assert result == {"headers": {"X-Auth-Token": "Token <TOKEN>"}}

    def test_cookie_without_login_config_placeholder(self) -> None:
        auth = AuthInfo(type="cookie")
        result = map_auth(auth)
        assert result == {"headers": {"Cookie": "<SESSION>"}}

    def test_login_config_without_helper_path_falls_through(self) -> None:
        """login_config present but no helper path → falls through to placeholder."""
        auth = AuthInfo(
            type="bearer_token",
            obtain_flow="login_form",
            login_config=LoginEndpointConfig(url="https://api.example.com/login"),
        )
        # No auth_helper_path → external-tool branch is skipped
        result = map_auth(auth, auth_helper_path=None)
        assert result == {"headers": {"Authorization": "Bearer <TOKEN>"}}


class TestGenerateRestishEntry:
    """Tests for generate_restish_entry."""

    def test_basic_entry(self) -> None:
        auth = AuthInfo(type="none")
        entry = generate_restish_entry(
            base_url="https://api.example.com",
            spec_path=Path("edf-api.yaml"),
            auth=auth,
        )
        assert entry["base"] == "https://api.example.com"
        assert entry["spec_files"] == ["edf-api.yaml"]
        assert "profiles" not in entry

    def test_entry_with_bearer_auth(self) -> None:
        auth = AuthInfo(type="bearer_token", token_prefix="Bearer")
        entry = generate_restish_entry(
            base_url="https://api.example.com",
            spec_path=Path("edf-api.yaml"),
            auth=auth,
        )
        assert "profiles" in entry
        profile = entry["profiles"]["default"]
        assert profile["headers"]["Authorization"] == "Bearer <TOKEN>"

    def test_entry_with_external_tool(self) -> None:
        auth = AuthInfo(
            type="bearer_token",
            obtain_flow="login_form",
            login_config=LoginEndpointConfig(url="https://api.example.com/login"),
        )
        entry = generate_restish_entry(
            base_url="https://api.example.com",
            spec_path=Path("edf-api.yaml"),
            auth=auth,
            auth_helper_path="/home/user/edf-api-auth.py",
        )
        profile = entry["profiles"]["default"]
        assert profile["auth"]["name"] == "external-tool"
        assert "/home/user/edf-api-auth.py" in profile["auth"]["params"]["commandline"]


