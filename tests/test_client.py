"""Tests for the generic runtime API client."""

from unittest.mock import MagicMock, patch

import pytest

from cli.client import ApiClient
from cli.formats.api_spec import (
    ApiSpec,
    AuthInfo,
    EndpointSpec,
    LoginEndpointConfig,
    ParameterSpec,
    Protocols,
    RefreshEndpointConfig,
    RequestSpec,
    ResponseSpec,
    RestProtocol,
)


def _make_spec(
    auth: AuthInfo | None = None,
    endpoints: list[EndpointSpec] | None = None,
) -> ApiSpec:
    """Create a minimal ApiSpec for testing."""
    if auth is None:
        auth = AuthInfo(type="bearer_token", token_header="Authorization", token_prefix="Bearer")
    if endpoints is None:
        endpoints = [
            EndpointSpec(
                id="get_users",
                path="/api/users",
                method="GET",
                request=RequestSpec(parameters=[
                    ParameterSpec(name="limit", location="query", type="integer"),
                ]),
                responses=[ResponseSpec(status=200)],
            ),
            EndpointSpec(
                id="get_user",
                path="/api/users/{user_id}",
                method="GET",
                request=RequestSpec(parameters=[
                    ParameterSpec(name="user_id", location="path", type="string", required=True),
                ]),
                responses=[ResponseSpec(status=200)],
            ),
            EndpointSpec(
                id="create_user",
                path="/api/users",
                method="POST",
                request=RequestSpec(
                    content_type="application/json",
                    parameters=[
                        ParameterSpec(name="name", location="body", type="string", required=True),
                        ParameterSpec(name="email", location="body", type="string", required=True),
                    ],
                ),
                responses=[ResponseSpec(status=201)],
            ),
        ]
    return ApiSpec(
        name="Test API",
        auth=auth,
        protocols=Protocols(
            rest=RestProtocol(base_url="https://api.example.com", endpoints=endpoints),
        ),
    )


class TestApiClientInit:
    def test_init_with_token(self):
        spec = _make_spec()
        client = ApiClient(spec, token="my-token")
        assert client.session.headers.get("Authorization") == "Bearer my-token"

    def test_init_with_token_no_prefix(self):
        auth = AuthInfo(type="api_key", token_header="X-API-Key")
        spec = _make_spec(auth=auth)
        client = ApiClient(spec, token="key123")
        assert client.session.headers.get("X-API-Key") == "key123"

    def test_init_with_env_vars(self):
        spec = _make_spec()
        with patch.dict("os.environ", {"API_TOKEN": "env-token"}):
            client = ApiClient(spec)
        assert client.session.headers.get("Authorization") == "Bearer env-token"

    def test_init_with_base_url_override(self):
        spec = _make_spec()
        client = ApiClient(spec, token="tok", base_url="https://custom.example.com")
        assert client._base_url == "https://custom.example.com"

    def test_init_with_spec_path(self, tmp_path):
        spec = _make_spec()
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(spec.model_dump_json(by_alias=True))
        client = ApiClient(str(spec_path), token="tok")
        assert len(client.endpoints()) == 3

    def test_init_credentials_without_login_config_raises(self):
        spec = _make_spec()
        with pytest.raises(ValueError, match="login_config"):
            ApiClient(spec, username="user", password="pass")

    @patch("cli.client.requests.Session")
    def test_init_with_login(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "new-tok", "refresh_token": "ref-tok"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        auth = AuthInfo(
            type="bearer_token",
            token_header="Authorization",
            token_prefix="Bearer",
            login_config=LoginEndpointConfig(
                url="/auth/login",
                credential_fields={"email": "username", "password": "password"},
                token_response_path="access_token",
                refresh_token_response_path="refresh_token",
            ),
        )
        spec = _make_spec(auth=auth)
        client = ApiClient(spec, username="user@example.com", password="secret")

        mock_session.request.assert_called_once()
        call_args = mock_session.request.call_args
        assert call_args[0] == ("POST", "https://api.example.com/auth/login")
        body = call_args[1]["json"]
        assert body["email"] == "user@example.com"
        assert body["password"] == "secret"
        assert mock_session.headers.get("Authorization") == "Bearer new-tok"
        assert client._refresh_token_value == "ref-tok"


class TestApiClientEndpoints:
    def test_list_endpoints(self):
        spec = _make_spec()
        client = ApiClient(spec, token="tok")
        eps = client.endpoints()
        assert len(eps) == 3
        ids = [e["id"] for e in eps]
        assert "get_users" in ids
        assert "get_user" in ids
        assert "create_user" in ids


class TestApiClientCall:
    @patch("cli.client.requests.Session")
    def test_call_get_with_query(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'[{"id": 1}]'
        mock_resp.json.return_value = [{"id": 1}]
        mock_resp.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        spec = _make_spec()
        client = ApiClient(spec, token="tok")
        client.call("get_users", limit="10")

        mock_session.request.assert_called_once()
        call_args = mock_session.request.call_args
        assert call_args[0] == ("GET", "https://api.example.com/api/users")
        assert call_args[1]["params"] == {"limit": "10"}

    @patch("cli.client.requests.Session")
    def test_call_get_with_path_param(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"id": "42"}'
        mock_resp.json.return_value = {"id": "42"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        spec = _make_spec()
        client = ApiClient(spec, token="tok")
        client.call("get_user", user_id="42")

        call_args = mock_session.request.call_args
        assert call_args[0] == ("GET", "https://api.example.com/api/users/42")

    @patch("cli.client.requests.Session")
    def test_call_post_with_body(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.content = b'{"id": "new"}'
        mock_resp.json.return_value = {"id": "new"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        spec = _make_spec()
        client = ApiClient(spec, token="tok")
        client.call("create_user", name="Alice", email="alice@example.com")

        call_args = mock_session.request.call_args
        assert call_args[0] == ("POST", "https://api.example.com/api/users")
        assert call_args[1]["json"] == {"name": "Alice", "email": "alice@example.com"}

    def test_call_unknown_endpoint_raises(self):
        spec = _make_spec()
        client = ApiClient(spec, token="tok")
        with pytest.raises(ValueError, match="Unknown endpoint"):
            client.call("nonexistent")

    @patch("cli.client.requests.Session")
    def test_call_refresh_on_401(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_session_cls.return_value = mock_session

        # First call returns 401, then refresh succeeds, then retry succeeds
        resp_401 = MagicMock()
        resp_401.status_code = 401

        resp_refresh = MagicMock()
        resp_refresh.status_code = 200
        resp_refresh.json.return_value = {"access_token": "refreshed-tok"}

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.content = b'{"ok": true}'
        resp_ok.json.return_value = {"ok": True}
        resp_ok.raise_for_status = MagicMock()

        mock_session.request.side_effect = [resp_401, resp_refresh, resp_ok]

        auth = AuthInfo(
            type="bearer_token",
            token_header="Authorization",
            token_prefix="Bearer",
            refresh_config=RefreshEndpointConfig(
                url="https://auth.example.com/token",
                token_field="refresh_token",
                extra_fields={"grant_type": "refresh_token"},
                token_response_path="access_token",
            ),
        )
        spec = _make_spec(auth=auth)
        client = ApiClient(spec, token="old-tok")
        client._refresh_token_value = "my-refresh-token"

        result = client.call("get_users")
        assert result == {"ok": True}
        assert mock_session.request.call_count == 3

        # Verify refresh call
        refresh_call = mock_session.request.call_args_list[1]
        assert refresh_call[0] == ("POST", "https://auth.example.com/token")
        assert refresh_call[1]["json"]["refresh_token"] == "my-refresh-token"
        assert refresh_call[1]["json"]["grant_type"] == "refresh_token"

    @patch("cli.client.requests.Session")
    def test_call_no_content(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.content = b""
        mock_resp.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        spec = _make_spec()
        client = ApiClient(spec, token="tok")
        result = client.call("get_users")
        assert result is None


class TestApiClientCustomAuth:
    def test_api_key_header(self):
        auth = AuthInfo(type="api_key", token_header="X-API-Key")
        spec = _make_spec(auth=auth)
        client = ApiClient(spec, token="mykey")
        assert client.session.headers.get("X-API-Key") == "mykey"

    def test_custom_prefix(self):
        auth = AuthInfo(type="bearer_token", token_header="Authorization", token_prefix="Token")
        spec = _make_spec(auth=auth)
        client = ApiClient(spec, token="abc")
        assert client.session.headers.get("Authorization") == "Token abc"


class TestExtractPath:
    def test_simple_path(self):
        data = {"access_token": "tok123"}
        assert ApiClient._extract_path(data, "access_token") == "tok123"

    def test_nested_path(self):
        data = {"data": {"tokens": {"access_token": "nested-tok"}}}
        assert ApiClient._extract_path(data, "data.tokens.access_token") == "nested-tok"

    def test_missing_key(self):
        data = {"foo": "bar"}
        assert ApiClient._extract_path(data, "nonexistent") is None

    def test_empty_path(self):
        data = {"foo": "bar"}
        assert ApiClient._extract_path(data, "") is None

    def test_path_through_non_dict(self):
        data = {"foo": "bar"}
        assert ApiClient._extract_path(data, "foo.bar") is None


class TestLoginFlow:
    @patch("cli.client.requests.Session")
    def test_login_with_extra_fields(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "tok"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        auth = AuthInfo(
            type="bearer_token",
            token_header="Authorization",
            token_prefix="Bearer",
            login_config=LoginEndpointConfig(
                url="https://auth0.example.com/oauth/token",
                credential_fields={"username": "username", "password": "password"},
                extra_fields={"grant_type": "password", "client_id": "abc123", "audience": "https://api.example.com"},
                token_response_path="access_token",
            ),
        )
        spec = _make_spec(auth=auth)
        ApiClient(spec, username="user", password="pass")

        call_args = mock_session.request.call_args
        assert call_args[0] == ("POST", "https://auth0.example.com/oauth/token")
        body = call_args[1]["json"]
        assert body["username"] == "user"
        assert body["password"] == "pass"
        assert body["grant_type"] == "password"
        assert body["client_id"] == "abc123"
        assert body["audience"] == "https://api.example.com"

    @patch("cli.client.requests.Session")
    def test_login_form_urlencoded(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "tok"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        auth = AuthInfo(
            type="bearer_token",
            token_header="Authorization",
            token_prefix="Bearer",
            login_config=LoginEndpointConfig(
                url="/auth/token",
                credential_fields={"username": "email", "password": "password"},
                content_type="application/x-www-form-urlencoded",
                token_response_path="access_token",
            ),
        )
        spec = _make_spec(auth=auth)
        ApiClient(spec, username="user@x.com", password="secret")

        call_args = mock_session.request.call_args
        # Should use data= instead of json=
        assert "data" in call_args[1]
        assert "json" not in call_args[1]

    @patch("cli.client.requests.Session")
    def test_login_nested_token_path(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"auth": {"token": "nested-tok"}}}
        mock_resp.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        auth = AuthInfo(
            type="bearer_token",
            token_header="Authorization",
            token_prefix="Bearer",
            login_config=LoginEndpointConfig(
                url="/login",
                credential_fields={"email": "email", "password": "password"},
                token_response_path="data.auth.token",
            ),
        )
        spec = _make_spec(auth=auth)
        ApiClient(spec, username="user", password="pass")
        assert mock_session.headers["Authorization"] == "Bearer nested-tok"
