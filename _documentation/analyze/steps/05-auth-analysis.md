# Auth Branch — Auth Analysis

> `LLMStep[list[Trace], AuthInfo]`
>
> **In:** ALL traces (unfiltered) — **Out:** `AuthInfo`

[← Back to overview](./00-overview.md)

---

## Purpose

Detects the authentication mechanism from ALL captured traces. Runs in **parallel** with the main endpoint analysis branch since auth traces are often on external domains (Auth0, Okta, Cognito...) that would be eliminated by the base URL filter.

## Why ALL traces (unfiltered)

Auth flows commonly involve external identity providers:
- `POST https://auth0.example.com/oauth/token`
- `GET https://accounts.google.com/o/oauth2/auth`
- `POST https://cognito-idp.eu-west-1.amazonaws.com/`

These would be filtered out after base URL detection. The auth step must see the full picture.

## Input preparation

The step receives the full `list[Trace]` and internally builds a compact summary via `_prepare_auth_summary()`:
- Filters for auth-related traces (those with `Authorization` headers, auth URL keywords, `set-cookie`, 401/403 responses)
- Includes sanitized request/response headers and truncated body snippets
- Login-related POST requests (to `/auth`, `/login`, `/token`, etc.) are prioritized first
- If no auth-related traces found, includes the first 5 traces as fallback context

## Prompt

The prompt sends the prepared auth summaries as JSON and asks the LLM to identify auth type, obtain flow, token handling, login/refresh endpoints, and user journey.

No tools are used — the summary already includes relevant headers and body snippets.

## Output

`AuthInfo` with the following fields:

| Field | Description |
|---|---|
| `type` | `"bearer_token"`, `"oauth2"`, `"cookie"`, `"basic"`, `"api_key"` |
| `obtain_flow` | How tokens are obtained: `"oauth2_password"`, `"login_form"`, `"social_auth"` |
| `token_header` / `token_prefix` | e.g. `"Authorization"` / `"Bearer"` |
| `business_process` | Human description of the auth flow |
| `user_journey` | Ordered steps the user goes through to authenticate |
| `login_config` | `LoginEndpointConfig`: URL, method, credential fields, token path |
| `refresh_config` | `RefreshEndpointConfig` (optional) |
| `discovery_notes` | Free-form notes from the LLM |

## Validation (`_validate_output`)

Not yet implemented — currently best-effort (no validation, no retry).

## Configuration

| Parameter | Value |
|---|---|
| `max_tokens` | 2048 |

## Fallback

On parse error: returns empty `AuthInfo()`. Pipeline falls back to `_detect_auth_mechanical()` which does simple pattern matching on headers (Bearer → bearer_token, Basic → basic, auth cookies → cookie).
