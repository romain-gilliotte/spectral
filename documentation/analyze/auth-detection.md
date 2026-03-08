# Auth detection

The `spectral auth analyze` command examines all captured traces to detect how the application authenticates and generates a script to reproduce the flow.

## How it works

Auth analysis runs on **all** unfiltered traces, not just those matching the detected base URL. This is intentional — authentication providers often live on separate domains (Auth0, Okta, Cognito, Google accounts, etc.) and would be lost if only base URL traces were considered.

The LLM receives a summary of all traces (with auth-related traces marked) and can inspect individual traces in detail using the `inspect_trace` tool. It identifies the authentication mechanism — login endpoints, token format, credential fields, refresh flows — and generates a Python script that reproduces the flow.

Traces are flagged as auth-related when their URL contains auth keywords (login, token, oauth, etc.), when they carry an Authorization header, or when they returned a 401/403 status.

## Auth helper script

When the LLM identifies a reproducible auth flow, `auth analyze` generates `auth_acquire.py` in the app's managed storage directory. If no authentication mechanism is found in the traces, no script is generated. The script is protocol-agnostic — it works for both REST and GraphQL APIs.

### Two-layer architecture

The auth system has two clearly separated layers:

| Layer | Location | Responsibility |
|-------|----------|---------------|
| Token acquisition | LLM-generated script (`auth_acquire.py`) | Defines `acquire_token()` (no arguments, prompts the user via injected helpers) and optionally `refresh_token(current_refresh_token)`. Performs the actual HTTP calls to authenticate |
| Runtime framework | Spectral CLI (`cli/helpers/auth_runtime.py`) | Loads the script as a module, injects helper functions, calls the right function, converts the result to a `TokenState`, and writes `token.json` |

This separation means the LLM only generates the API-specific authentication logic. Token persistence, expiry management, and prompt helpers are handled by the spectral runtime and never vary between APIs.

### Capabilities

The generated script:

- Uses only Python standard library modules (no pip dependencies)
- Receives helpers injected by the runtime: `prompt_text(label)` and `prompt_secret(label)` to collect credentials interactively, `tell_user(message)` and `wait_user_confirmation(message)` to communicate with the user, and `debug(*args)` to log diagnostic output that is captured and shown to the LLM during interactive fix
- Performs the full authentication flow, including multi-step flows (e.g., request OTP, then verify)
- Reproduces non-standard request headers observed in the captured traffic (User-Agent, app version, etc.) to avoid client-identity rejections

The script is not run directly. Instead, use the managed auth commands: `spectral auth login` calls `acquire_token()`, `spectral auth refresh` calls `refresh_token()`, and both write the result to `token.json` in managed storage. For manual token injection, use `spectral auth set`.

## Extracting tokens from traces

As an alternative to generating a script, `spectral auth extract <app>` scans all captured traces for auth headers and writes them directly to `token.json`. This is useful when you already have authenticated traffic and just need to extract the token values. Unlike `auth analyze`, it does not produce a reusable script — the extracted tokens will expire and cannot be refreshed automatically.

## Interactive fix on login failure

When `spectral auth login` fails (the generated script raises an error), the command offers to fix the script interactively using the LLM. The fix loop sends the error details — including any output from the script's `debug()` calls — to the LLM, which rewrites the script and retries login automatically. This cycle repeats until login succeeds or the user cancels.

The MCP server reads tokens from `token.json` at request time and injects them into every outgoing request. See [Calling the API](../getting-started/calling-the-api.md) for details.
