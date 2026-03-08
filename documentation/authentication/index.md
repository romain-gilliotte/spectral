# Authentication

Spectral manages authentication so AI agents don't have to. When the MCP server makes a request on behalf of an agent, it automatically injects the right credentials — no manual header management, no token juggling.

## Paths to authentication

There are three ways to set up auth for an app, depending on your situation:

| Path | Commands | When to use |
|------|----------|-------------|
| **Generated script** | `auth analyze` then `auth login` | The app has a standard login flow (username/password, OAuth, OTP). Produces a reusable script that can acquire and refresh tokens. |
| **Direct extraction** | `auth extract` | You already have authenticated traffic in your captures. Fast, no LLM needed, but tokens are non-renewable. |
| **Manual injection** | `auth set -H` or `auth set -c` | The generated script doesn't work, or you have a token from another source. |

For most apps, start with `auth analyze` + `auth login`. Fall back to `auth extract` or `auth set` if the generated script doesn't work for your app.

## How the MCP server uses tokens

When a tool is called, the MCP server checks whether the tool requires authentication. If it does, the server:

1. Loads the stored token from `token.json` in the app's managed storage directory.
2. If the token has expired and a refresh function is available (from a generated auth script), it auto-refreshes before making the request.
3. Injects the token's headers into the outgoing HTTP request.

If no valid token is available and refresh fails, the server returns an error instructing the user to run `spectral auth login`.

This means AI agents never need to handle authentication themselves — it happens transparently.

## Token lifecycle

Tokens are stored in `token.json` within the app's managed storage directory (`~/.local/share/spectral/apps/<app>/token.json`). The file contains headers to inject, an optional refresh token, and an optional expiry timestamp.

| Action | What happens |
|--------|-------------|
| `auth login` | Runs the generated script, prompts for credentials, writes `token.json` |
| `auth extract` | Extracts headers from captured traces, writes `token.json` |
| `auth set` | Writes manually provided headers/cookies to `token.json` |
| `auth refresh` | Calls the script's refresh function, updates `token.json` |
| MCP server auto-refresh | Same as `auth refresh`, but triggered automatically at request time |
| `auth logout` | Deletes `token.json` |
