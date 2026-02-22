# Auth detection

The analyze command includes a dedicated auth analysis step that examines all captured traces to detect how the application authenticates.

## How it works

Auth analysis runs on **all** unfiltered traces, not just those matching the detected base URL. This is intentional — authentication providers often live on separate domains (Auth0, Okta, Cognito, Google accounts, etc.) and would be lost if only base URL traces were considered.

The LLM examines request and response patterns to identify:

| Field | Description |
|-------|-------------|
| Auth type | bearer_token, oauth2, cookie, basic, api_key, or none |
| Obtain flow | How tokens are obtained: OAuth2 variants, login form, OTP/SMS, API key, social auth |
| Token header | Which header carries the auth credential (Authorization, Cookie, X-API-Key, etc.) |
| Token prefix | Prefix before the token value (Bearer, Basic, or none) |
| Business process | Human-readable description of the authentication flow |
| User journey | Step-by-step sequence of what the user does to authenticate |

## Login and refresh detection

When the LLM identifies a login endpoint, it extracts:

- The endpoint URL and HTTP method
- Credential fields with human descriptions (e.g., "your email address", "your password")
- Extra constant fields sent with every login request (e.g., grant_type, country code)
- The JSON path to the access token in the response
- The JSON path to the refresh token, if present

If a token refresh endpoint is detected, its URL, method, and field mapping are also extracted.

## Auth helper script

When the detected auth flow is reproducible (has a clear login endpoint with known credential fields), the pipeline generates a standalone Python auth helper script (`<name>-auth.py`). The script is protocol-agnostic — it works for both REST and GraphQL APIs.

### Two-layer architecture

The auth helper has two clearly separated layers:

| Layer | Source | Responsibility |
|-------|--------|---------------|
| Token acquisition | LLM-generated | Performs the actual HTTP calls to authenticate (login endpoint, OTP flow, etc.) — a pure `acquire_token(credentials)` function and optionally `refresh_token(current_refresh_token)` |
| Framework | Static, always identical | Token caching, expiry checking, credential prompting, Restish adapter, standalone token mode |

This separation means the LLM only generates the API-specific authentication logic. Caching, expiry, prompting, and output modes are handled by the framework and never vary between APIs.

### Capabilities

The generated script:

- Uses only Python standard library modules (no pip dependencies)
- Prompts the user interactively for credentials (via `/dev/tty`)
- Performs the full authentication flow, including multi-step flows (e.g., request OTP, then verify)
- Caches the token to `~/.cache/spectral/<api-name>/token.json`
- Checks token expiry (JWT `exp` claim or TTL fallback) and refreshes automatically when possible

### Two modes

The script supports two invocation modes:

| Mode | Command | Behavior |
|------|---------|----------|
| Default (token) | `python3 <name>-auth.py` | Prints a valid token to stdout — for use with curl, GraphQL clients, scripting, any tool |
| Restish | `python3 <name>-auth.py --restish` | Restish external-tool contract: reads JSON from stdin, injects auth header, writes JSON to stdout |

The default mode makes the auth helper useful beyond Restish. Any tool or script that needs a token can call the helper and capture its stdout.

## Mechanical fallback

If the LLM auth analysis fails or produces invalid output, the pipeline falls back to mechanical auth detection. This examines trace headers for common auth patterns (Authorization header with Bearer/Basic prefix, API key headers, session cookies) and produces a simpler AuthInfo without business descriptions or login/refresh configuration.

## Restish integration

The generated Restish configuration (`<name>.restish.json`) includes the auth setup. When an auth helper script was generated, the config references it as an `external-tool` auth provider with the `--restish` flag. When only static auth was detected (e.g., a fixed API key), the config includes placeholder values that the user must fill in manually.

See [Calling the API](../getting-started/calling-the-api.md) for details on using the generated configuration.
