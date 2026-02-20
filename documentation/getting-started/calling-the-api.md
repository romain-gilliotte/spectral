# Calling the API

After running `spectral analyze`, you have an API spec and a Restish configuration file. This guide shows how to use them to actually call the API from the command line.

## Install Restish

[Restish](https://rest.sh/) is a CLI for interacting with REST APIs. It understands OpenAPI specs and provides tab completion, authentication, and human-readable output.

=== "macOS"

    ```bash
    brew install danielgtaylor/restish/restish
    ```

=== "Go"

    ```bash
    go install github.com/danielgtaylor/restish@latest
    ```

## Load the configuration

The analyze command produces a `<name>.restish.json` file containing a single API entry. Merge it into your Restish configuration:

```bash
restish api edit < myapp-api.restish.json
```

Alternatively, copy the entry manually into `~/.config/restish/apis.json` under a key of your choice (the analyze command uses the output name).

## List available operations

Once the API is registered, Restish discovers all operations from the OpenAPI spec:

```bash
restish myapp-api --help
```

This lists every operation with its summary and HTTP method. Use tab completion to explore endpoints.

## Make a first call

Pick an operation from the list and call it:

```bash
restish myapp-api get-user-profile
```

Restish sends the request with the configured base URL and authentication, then displays the response with syntax highlighting.

## Authentication

### Interactive auth (auth helper script)

When the analyze command detects an authentication flow it can reproduce, it generates a Python auth helper script (`<name>-auth.py`). The Restish configuration references this script as an external tool.

On the first API call, Restish invokes the script, which prompts you for credentials (username, password, OTP code, etc.) via the terminal. The script performs the full authentication flow, caches the resulting token, and injects it into the request headers.

On subsequent calls, the script reuses the cached token. When the token expires, it either refreshes it automatically (if a refresh endpoint was detected) or prompts you again.

!!! info
    The auth script reads user input from `/dev/tty` rather than stdin, because Restish uses stdin to pipe the request JSON to the script. Prompts and error messages also go to `/dev/tty` so they remain visible.

Token cache location: `~/.cache/spectral/<api-name>/token.json`.

### Static auth (manual placeholders)

If the generated Restish config contains placeholder values like `<TOKEN>` or `<API_KEY>`, replace them with actual credentials. The analyze command prints a warning listing any placeholders that need filling in.

You can edit the API configuration at any time:

```bash
restish api edit myapp-api
```

## Troubleshooting

If a call returns an authentication error (401 or 403), the token may have expired. Delete the cached token to force re-authentication:

```bash
rm ~/.cache/spectral/myapp-api/token.json
```

If the auth helper script fails entirely, you can fall back to static auth: remove the `external-tool` auth configuration from Restish and set the token header manually.
