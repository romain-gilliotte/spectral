"""Generic runtime API client that reads an enriched API spec and handles auth, refresh, and calls."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

from cli.formats.api_spec import ApiSpec


class ApiClient:
    """A generic API client driven by an enriched API spec JSON.

    Handles authentication (login, refresh, token injection) and routes
    call parameters to path/query/body based on the spec.
    """

    def __init__(
        self,
        spec: str | Path | ApiSpec,
        *,
        base_url: str | None = None,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        if isinstance(spec, ApiSpec):
            self._spec = spec
        else:
            self._spec = ApiSpec.model_validate_json(Path(spec).read_text())

        self._session = requests.Session()
        self._refresh_token_value: str | None = None

        # Resolve base URL
        self._base_url = (
            base_url
            or os.environ.get("API_BASE_URL")
            or self._spec.protocols.rest.base_url
        ).rstrip("/")

        # Resolve auth
        token = token or os.environ.get("API_TOKEN")
        username = username or os.environ.get("API_USERNAME")
        password = password or os.environ.get("API_PASSWORD")

        if token:
            self._set_auth_header(token)
        elif username and password and self._spec.auth.login_config:
            self._login(username, password)
        elif username and password:
            raise ValueError(
                "Credentials provided but no login_config in spec. "
                "Provide a token instead, or add login_config to the spec."
            )

    @property
    def session(self) -> requests.Session:
        return self._session

    def endpoints(self) -> list[dict]:
        """List available endpoints (id, method, path, purpose)."""
        return [
            {
                "id": ep.id,
                "method": ep.method,
                "path": ep.path,
                "purpose": ep.business_purpose or "",
            }
            for ep in self._spec.protocols.rest.endpoints
        ]

    def call(self, endpoint_id: str, **kwargs: Any) -> Any:
        """Call an endpoint by its ID, routing kwargs to path/query/body.

        On 401 with a refresh_config available, attempts a token refresh
        and retries the request once.
        """
        endpoint = None
        for ep in self._spec.protocols.rest.endpoints:
            if ep.id == endpoint_id:
                endpoint = ep
                break
        if endpoint is None:
            raise ValueError(
                f"Unknown endpoint '{endpoint_id}'. "
                f"Available: {[ep.id for ep in self._spec.protocols.rest.endpoints]}"
            )

        response = self._do_call(endpoint, kwargs)

        # Auto-refresh on 401
        if response.status_code == 401 and self._refresh_token_value and self._spec.auth.refresh_config:
            if self._refresh_token():
                response = self._do_call(endpoint, kwargs)

        response.raise_for_status()

        if response.content:
            try:
                return response.json()
            except ValueError:
                return response.text
        return None

    def _do_call(self, endpoint, kwargs: dict) -> requests.Response:
        """Execute the HTTP request for an endpoint."""
        # Classify params
        param_locations: dict[str, str] = {}
        for p in endpoint.request.parameters:
            param_locations[p.name] = p.location

        path_params: dict[str, str] = {}
        query_params: dict[str, Any] = {}
        body_params: dict[str, Any] = {}

        for key, value in kwargs.items():
            location = param_locations.get(key, "body")
            if location == "path":
                path_params[key] = str(value)
            elif location == "query":
                query_params[key] = value
            else:
                body_params[key] = value

        # Build URL
        path = endpoint.path
        for name, value in path_params.items():
            path = path.replace("{" + name + "}", value)
        url = f"{self._base_url}{path}"

        method = endpoint.method.upper()
        request_kwargs: dict[str, Any] = {"params": query_params or None}
        if body_params:
            request_kwargs["json"] = body_params

        return self._session.request(method, url, **request_kwargs)

    def _login(self, username: str, password: str) -> None:
        """Programmatic login via login_config."""
        config = self._spec.auth.login_config
        if config is None:
            raise ValueError("No login_config in spec")

        # Build request body
        body: dict[str, str] = {}
        for field_name, credential_key in config.credential_fields.items():
            if credential_key == "username" or credential_key == "email":
                body[field_name] = username
            elif credential_key == "password":
                body[field_name] = password
            else:
                body[field_name] = credential_key
        body.update(config.extra_fields)

        url = self._resolve_url(config.url)

        if config.content_type == "application/x-www-form-urlencoded":
            resp = self._session.request(config.method, url, data=body)
        else:
            resp = self._session.request(config.method, url, json=body)
        resp.raise_for_status()

        data = resp.json()
        token = self._extract_path(data, config.token_response_path)
        if not token:
            raise ValueError(
                f"Could not extract token from login response at path '{config.token_response_path}'"
            )
        self._set_auth_header(str(token))

        # Extract refresh token if configured
        if config.refresh_token_response_path:
            rt = self._extract_path(data, config.refresh_token_response_path)
            if rt:
                self._refresh_token_value = str(rt)

    def _refresh_token(self) -> bool:
        """Refresh the access token via refresh_config. Returns True on success."""
        config = self._spec.auth.refresh_config
        if config is None or not self._refresh_token_value:
            return False

        body: dict[str, str] = {config.token_field: self._refresh_token_value}
        body.update(config.extra_fields)

        url = self._resolve_url(config.url)

        if config.content_type == "application/x-www-form-urlencoded":
            resp = self._session.request(config.method, url, data=body)
        else:
            resp = self._session.request(config.method, url, json=body)

        if resp.status_code >= 400:
            return False

        data = resp.json()
        token = self._extract_path(data, config.token_response_path)
        if not token:
            return False

        self._set_auth_header(str(token))
        return True

    def _set_auth_header(self, token: str) -> None:
        """Place the token in the correct header based on the spec."""
        header = self._spec.auth.token_header or "Authorization"
        prefix = self._spec.auth.token_prefix
        if prefix:
            self._session.headers[header] = f"{prefix} {token}"
        else:
            self._session.headers[header] = token

    def _resolve_url(self, url: str) -> str:
        """Resolve a URL: absolute if starts with http, else relative to base_url."""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return f"{self._base_url}{url}"

    @staticmethod
    def _extract_path(data: dict, dot_path: str) -> Any:
        """Traverse a dict with dot-notation: 'data.access_token' -> data["data"]["access_token"]."""
        if not dot_path:
            return None
        current: Any = data
        for key in dot_path.split("."):
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None
        return current
