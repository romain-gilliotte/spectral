# Authentication Specification

The `auth` section of the enriched API spec describes how the application authenticates its users. It combines mechanical detection (what headers and tokens were observed) with LLM inference (what the authentication flow means for a human user).

Authentication analysis runs as a parallel branch in the pipeline, examining ALL captured traces — including those to external identity providers that are filtered out of the main endpoint analysis. This is critical because auth flows commonly involve third-party domains (Auth0, Okta, Cognito, Google, etc.).

---

## Auth types

The `type` field identifies the authentication mechanism observed in captured traffic.

| Type | Detection signal | Description |
|---|---|---|
| `bearer_token` | `Authorization: Bearer ...` header | Token-based auth, most common in modern APIs |
| `oauth2` | OAuth2 token exchange flows observed | OAuth2 with specific grant type in `obtain_flow` |
| `cookie` | Session cookies in request/response | Cookie-based session auth |
| `basic` | `Authorization: Basic ...` header | HTTP Basic authentication |
| `api_key` | API key in header or query parameter | Key-based auth (X-API-Key, api_key param, etc.) |

Detection starts mechanically: the pipeline scans all trace headers for known auth patterns. The LLM then refines the classification, distinguishing (for example) a bearer token obtained via OAuth2 password grant from one obtained via authorization code flow.

When multiple auth mechanisms are observed (e.g. cookies for the web session plus bearer tokens for API calls), the LLM identifies the primary mechanism used for API authentication.

---

## AuthInfo fields

| Field | Type | Source | Description |
|---|---|---|---|
| `type` | string | Mixed | Auth mechanism identifier (see table above) |
| `obtain_flow` | string | LLM-inferred | How tokens are obtained: `oauth2_authorization_code`, `oauth2_password`, `login_form`, `social_auth`, `api_key_static` |
| `business_process` | string or null | LLM-inferred | Human description of the auth experience: "Two-factor authentication with SMS verification" |
| `user_journey` | list of strings | LLM-inferred | Ordered steps the user goes through to authenticate |
| `token_header` | string or null | Mechanical | Header name carrying the token (typically `Authorization`) |
| `token_prefix` | string or null | Mechanical | Prefix before the token value (typically `Bearer`) |
| `login_config` | LoginEndpointConfig or null | Mixed | Structured login endpoint configuration |
| `refresh_config` | RefreshEndpointConfig or null | Mixed | Structured token refresh configuration |
| `discovery_notes` | string or null | LLM-inferred | Additional observations: token lifetime, redirect behavior, error handling |

---

## User journey

The `user_journey` field reconstructs the human authentication experience as an ordered list of steps. The LLM infers this from captured UI context (login page forms, SMS verification screens, error messages) combined with the observed network flow (token requests, redirects, cookie exchanges).

A typical user journey might contain entries like:
- "Enter email and password on the login page"
- "Receive SMS verification code"
- "Enter the 6-digit code on the verification screen"
- "Access granted — session token valid for approximately 24 hours"

This is one of the most valuable LLM-inferred fields for documentation. It translates a sequence of HTTP requests into a narrative that a developer can understand without reading packet captures.

**Limitations:** The user journey can only describe what the user actually did during capture. If the user logged in with a password but the application also supports social login, the social login path will not appear in the journey. If the user's token never expired during the session, the refresh flow may be inferred from observed refresh endpoints but not from direct experience.

---

## Login configuration

When a login endpoint is identified, `login_config` provides the structured details needed to programmatically reproduce the login flow.

### LoginEndpointConfig

| Field | Type | Source | Description |
|---|---|---|---|
| `url` | string | Mechanical | Full URL of the login endpoint |
| `method` | string | Mechanical | HTTP method (typically POST) |
| `credential_fields` | dict (field name → description) | Mixed | Fields that carry credentials: `{"email": "user email", "password": "user password"}` |
| `extra_fields` | dict (field name → value) | Mechanical | Additional fields observed in login requests (client_id, grant_type, scope, etc.) |
| `content_type` | string | Mechanical | Request Content-Type |
| `token_response_path` | string | Mixed | JSON path to the access token in the response body (e.g. `access_token`, `data.token`) |
| `refresh_token_response_path` | string | Mixed | JSON path to the refresh token, if present |

The `credential_fields` dictionary maps field names to descriptions. The actual credential values are never stored — only the field names and their roles. This allows code generators to produce login methods with named parameters.

`extra_fields` captures non-credential fields that are required for login — OAuth2 `grant_type`, `client_id`, `scope`, etc. These are observed values from captured traffic.

---

## Refresh configuration

When a token refresh endpoint is identified, `refresh_config` provides the details needed to implement automatic token renewal.

### RefreshEndpointConfig

| Field | Type | Source | Description |
|---|---|---|---|
| `url` | string | Mechanical | Full URL of the refresh endpoint |
| `method` | string | Mechanical | HTTP method (typically POST) |
| `token_field` | string | Mechanical | Field name carrying the refresh token in the request body |
| `extra_fields` | dict (field name → value) | Mechanical | Additional fields (grant_type, client_id, etc.) |
| `token_response_path` | string | Mixed | JSON path to the new access token in the response |
| `content_type` | string | Mechanical | Request Content-Type |

Refresh configuration is only populated if a refresh flow was actually observed during capture (the user's token expired and was refreshed) or if the LLM identified a clear refresh endpoint from the traffic patterns.

---

## Mechanical fallback

If the LLM auth analysis fails (parse error, unexpected response), the pipeline falls back to mechanical auth detection. This simpler approach examines request headers across all traces and classifies based on patterns:

| Pattern observed | Mechanical classification |
|---|---|
| `Authorization: Bearer ...` | `type: "bearer_token"` |
| `Authorization: Basic ...` | `type: "basic"` |
| Auth-related cookies (session, token) | `type: "cookie"` |
| X-API-Key or similar header | `type: "api_key"` |

The mechanical fallback populates `type`, `token_header`, and `token_prefix` but cannot infer `business_process`, `user_journey`, `login_config`, or `refresh_config`. These fields remain empty, and generators should handle their absence gracefully.

---

## How generators use auth

Each generator consumes auth information differently:

| Generator | Auth usage |
|---|---|
| **OpenAPI** | Security schemes, security requirements on operations |
| **Python client** | Constructor auth parameters, `login()` and `refresh()` methods built from configs |
| **Markdown docs** | Dedicated authentication page with user journey narrative, setup instructions |
| **cURL scripts** | Auth header in every example, login script if login_config present |
| **MCP server** | Auth configuration in server setup, token management in tool implementations |
