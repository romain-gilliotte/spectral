"""Step: Analyze authentication mechanism using LLM."""

from __future__ import annotations

import json
from typing import Any, cast

from cli.commands.analyze.steps.base import LLMStep
from cli.commands.analyze.steps.types import (
    AuthInfo,
    LoginEndpointConfig,
    RefreshEndpointConfig,
)
from cli.commands.analyze.utils import (
    get_header,
    sanitize_headers,
    truncate_json,
)
from cli.commands.capture.types import Trace
import cli.helpers.llm as llm


class AnalyzeAuthStep(LLMStep[list[Trace], AuthInfo]):
    """Analyze authentication mechanism from traces using LLM.

    Input: ALL traces (not just filtered ones — external auth providers may be on different domains).
    Output: AuthInfo with detected authentication info.
    """

    name = "analyze_auth"

    async def _execute(self, input: list[Trace]) -> AuthInfo:
        auth_summary: list[dict[str, Any]] = _prepare_auth_summary(input)

        prompt = f"""Analyze the authentication mechanism used by this web application.

Here are relevant traces (login flows, token exchanges, authenticated requests):

{json.dumps(auth_summary)[:8000]}

Identify:
1. "type": The auth type (e.g., "bearer_token", "oauth2", "cookie", "basic", "api_key", "none")
2. "obtain_flow": How the token is obtained (e.g., "oauth2_authorization_code", "oauth2_password", "oauth2_client_credentials", "login_form", "otp_sms", "api_key", "social_auth")
3. "token_header": The header carrying the auth token (e.g., "Authorization", "X-API-Key", "Cookie")
4. "token_prefix": The prefix before the token value (e.g., "Bearer", "Basic", null)
5. "business_process": Human description of how auth works
6. "user_journey": Array of string steps describing the login process (e.g., ["Enter phone number", "Receive SMS code", "Submit code"])
7. "discovery_notes": Any additional observations
8. "login_endpoint": If a login/token endpoint is visible, provide an object with these fields:
   - "url": full URL of the endpoint
   - "method": HTTP method (usually "POST")
   - "credential_fields": object mapping each user-supplied field name to a SHORT HUMAN DESCRIPTION of what the user should enter — NOT the observed value from the trace. Example: {{"email": "your email address", "password": "your password"}}. For OTP flows: {{"phoneNumber": "phone number with country prefix", "verificationCode": "SMS verification code"}}
   - "extra_fields": object with FIXED fields that are always sent with the same value (e.g., {{"grant_type": "password", "countryCode": "FR"}}). These are constants, not user input. Only include fields whose value is always the same across requests.
   - "token_response_path": dot-separated path to the access token in the JSON response body (e.g., "access_token", "data.token", "result.jwt"). Must be a valid path that resolves to the token string when walking the response JSON object key by key. If the token is not directly accessible via a simple JSON path (e.g., embedded in a URL query parameter, inside an encoded string, or wrapped in a non-JSON format), set this to "" and explain the extraction difficulty in discovery_notes.
   - "refresh_token_response_path": dot-separated path to the refresh token in the response, or "" if none
   Set login_endpoint to null if no login endpoint is visible.
9. "refresh_endpoint_config": If a refresh/token-refresh endpoint is visible, provide:
   {{"url": "full URL", "method": "POST", "token_field": "refresh_token", "extra_fields": {{}}, "token_response_path": "access_token"}}
   Set to null if no refresh endpoint is visible.

Look for these patterns:
- Auth0/Okta/Cognito IdP domains (external token endpoints with grant_type, client_id)
- Login form POST endpoints (email/password → JWT token)
- OAuth2 password grant (grant_type=password)
- OTP/SMS verification flows (phone number + verification code)
- Custom auth headers: X-API-Key, X-Auth-Token, X-Access-Token
- If the token endpoint is on an external domain, use the full URL.

Respond in JSON."""

        response: Any = await llm.create(
            label="analyze_auth",
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        llm.save_debug("analyze_auth", prompt, response.content[0].text)
        data = llm.extract_json(response.content[0].text)
        if not isinstance(data, dict):
            return AuthInfo()

        login_config = None
        login_data_raw: Any = data.get("login_endpoint")
        if isinstance(login_data_raw, dict) and cast(
            dict[str, Any], login_data_raw
        ).get("url"):
            ld = cast(dict[str, Any], login_data_raw)
            login_config = LoginEndpointConfig(
                url=str(ld["url"]),
                method=str(ld.get("method", "POST")),
                credential_fields=ld.get("credential_fields", {}),
                extra_fields=ld.get("extra_fields", {}),
                token_response_path=str(ld.get("token_response_path", "access_token")),
                refresh_token_response_path=str(
                    ld.get("refresh_token_response_path", "")
                ),
            )

        refresh_config = None
        refresh_data_raw: Any = data.get("refresh_endpoint_config")
        if isinstance(refresh_data_raw, dict) and cast(
            dict[str, Any], refresh_data_raw
        ).get("url"):
            rd = cast(dict[str, Any], refresh_data_raw)
            refresh_config = RefreshEndpointConfig(
                url=str(rd["url"]),
                method=str(rd.get("method", "POST")),
                token_field=str(rd.get("token_field", "refresh_token")),
                extra_fields=rd.get("extra_fields", {}),
                token_response_path=str(rd.get("token_response_path", "access_token")),
            )

        return AuthInfo(
            type=str(data.get("type", "")),
            obtain_flow=str(data.get("obtain_flow", "")),
            business_process=data.get("business_process"),
            user_journey=data.get("user_journey", []),
            token_header=data.get("token_header"),
            token_prefix=data.get("token_prefix"),
            login_config=login_config,
            refresh_config=refresh_config,
            discovery_notes=data.get("discovery_notes"),
        )


def _prepare_auth_summary(traces: list[Trace]) -> list[dict[str, Any]]:
    """Prepare trace summaries relevant to authentication."""
    _AUTH_URL_KEYWORDS = [
        "auth",
        "login",
        "token",
        "oauth",
        "callback",
        "session",
        "signin",
        "auth0",
        "okta",
        "cognito",
        "accounts.google",
    ]
    _LOGIN_URL_KEYWORDS = ["auth", "login", "signin", "token"]

    summaries: list[dict[str, Any]] = []
    login_summaries: list[dict[str, Any]] = []

    for t in traces:
        headers_dict = {h.name: h.value for h in t.meta.request.headers}
        resp_headers_dict = {h.name: h.value for h in t.meta.response.headers}
        req_header_names_lower = {h.name.lower() for h in t.meta.request.headers}

        is_auth_related = (
            "authorization" in req_header_names_lower
            or any(
                h in req_header_names_lower
                for h in ["x-api-key", "x-auth-token", "x-access-token"]
            )
            or "set-cookie" in {h.name.lower() for h in t.meta.response.headers}
            or any(kw in t.meta.request.url.lower() for kw in _AUTH_URL_KEYWORDS)
            or t.meta.response.status in (401, 403)
        )

        if not is_auth_related:
            continue

        url_lower = t.meta.request.url.lower()
        is_login_post = t.meta.request.method.upper() == "POST" and any(
            kw in url_lower for kw in _LOGIN_URL_KEYWORDS
        )

        summary: dict[str, Any] = {
            "method": t.meta.request.method,
            "url": t.meta.request.url,
            "response_status": t.meta.response.status,
            "request_headers": sanitize_headers(headers_dict),
            "response_headers": sanitize_headers(resp_headers_dict),
        }

        body_max_keys = 15 if is_login_post else 5

        if t.request_body:
            try:
                body = json.loads(t.request_body)
                summary["request_body_snippet"] = truncate_json(
                    body, max_keys=body_max_keys
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        if t.response_body:
            try:
                body = json.loads(t.response_body)
                summary["response_body_snippet"] = truncate_json(
                    body, max_keys=body_max_keys
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        if is_login_post:
            login_summaries.append(summary)
        else:
            summaries.append(summary)

    summaries = login_summaries + summaries

    if not summaries and traces:
        for t in traces[:5]:
            headers_dict = {h.name: h.value for h in t.meta.request.headers}
            summaries.append(
                {
                    "method": t.meta.request.method,
                    "url": t.meta.request.url,
                    "response_status": t.meta.response.status,
                    "request_headers": sanitize_headers(headers_dict),
                }
            )

    return summaries


def detect_auth_mechanical(traces: list[Trace]) -> AuthInfo:
    """Fallback mechanical auth detection."""
    auth_type = ""
    token_header = None
    token_prefix = None

    for trace in traces:
        auth_value = get_header(trace.meta.request.headers, "authorization")
        if auth_value:
            token_header = "Authorization"
            if auth_value.startswith("Bearer "):
                auth_type = "bearer_token"
                token_prefix = "Bearer"
            elif auth_value.startswith("Basic "):
                auth_type = "basic"
                token_prefix = "Basic"
            else:
                auth_type = "custom"
            break

    if not auth_type:
        custom_headers = ["x-api-key", "x-auth-token", "x-access-token"]
        for trace in traces:
            for h in trace.meta.request.headers:
                if h.name.lower() in custom_headers:
                    auth_type = "api_key"
                    token_header = h.name
                    break
            if auth_type:
                break

    if not auth_type:
        for trace in traces:
            cookie = get_header(trace.meta.request.headers, "cookie")
            if cookie and any(
                name in cookie.lower() for name in ["session", "token", "auth", "jwt"]
            ):
                auth_type = "cookie"
                break

    return AuthInfo(
        type=auth_type, token_header=token_header, token_prefix=token_prefix
    )
