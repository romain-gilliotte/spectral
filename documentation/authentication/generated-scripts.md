# Generated auth scripts

The `spectral auth analyze` command examines all captured traces to detect how the application authenticates and generates a Python script to reproduce the flow.

## How `auth analyze` works

Auth analysis runs on **all** unfiltered traces, not just those matching the detected base URL. This is intentional — authentication providers often live on separate domains (Auth0, Okta, Cognito, Google accounts, etc.) and would be lost if only base URL traces were considered.

The LLM receives a summary of all traces (with auth-related traces marked) and can inspect individual traces in detail using the `inspect_trace` tool. It identifies the authentication mechanism — login endpoints, token format, credential fields, refresh flows — and generates a Python script that reproduces the flow.

Traces are flagged as auth-related when their URL contains auth keywords (login, token, oauth, etc.), when they carry an Authorization header, or when they returned a 401/403 status.

## The generated script

When the LLM identifies a reproducible auth flow, `auth analyze` generates `auth_acquire.py` in the app's managed storage directory. If no authentication mechanism is found in the traces, no script is generated.

The generated script:

- Uses only Python standard library modules (no pip dependencies)
- Receives helpers injected by the runtime: `prompt_text(label)` and `prompt_secret(label)` to collect credentials interactively, `tell_user(message)` and `wait_user_confirmation(message)` to communicate with the user, and `debug(*args)` to log diagnostic output
- Performs the full authentication flow, including multi-step flows (e.g., request OTP, then verify)
- Reproduces non-standard request headers observed in the captured traffic (User-Agent, app version, etc.) to avoid client-identity rejections

## Running `auth login`

The `spectral auth login` command loads the generated `auth_acquire.py` script, calls `acquire_token()` (which prompts for credentials), and writes the result to `token.json`.

## Auto-correction on failure

When `auth login` fails (the generated script raises an error), the command offers to fix the script interactively using the LLM. The fix loop sends the error details — including any output from the script's `debug()` calls — to the LLM, which rewrites the script and retries login automatically. This cycle repeats until login succeeds or the user cancels.

## Two-layer architecture

The auth system has two clearly separated layers:

| Layer | Location | Responsibility |
|-------|----------|---------------|
| Token acquisition | LLM-generated script (`auth_acquire.py`) | Defines `acquire_token()` (no arguments, prompts the user via injected helpers) and optionally `refresh_token(current_refresh_token)`. Performs the actual HTTP calls to authenticate. |
| Runtime framework | Spectral CLI (`cli/helpers/auth_runtime.py`) | Loads the script as a module, injects helper functions, calls the right function, converts the result to a `TokenState`, and writes `token.json`. |

This separation means the LLM only generates the API-specific authentication logic. Token persistence, expiry management, and prompt helpers are handled by the Spectral runtime and never vary between APIs.

## Refreshing tokens

The `spectral auth refresh` command loads `token.json`, calls `refresh_token()` from the auth script with the current refresh token, and updates `token.json` with the new token. This requires both `token.json` and `auth_acquire.py` to exist.

The MCP server performs this same refresh automatically when it detects an expired token before making a request, so manual refresh is rarely needed.
