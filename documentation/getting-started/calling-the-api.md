# Calling the API

After running `spectral analyze`, you have an API spec and configuration files. This guide shows how to use them to actually call the API from the command line.

## REST APIs with Restish

### Install Restish

[Restish](https://rest.sh/) is a CLI for interacting with REST APIs. It understands OpenAPI specs and provides tab completion, authentication, and human-readable output.

=== "macOS"

    ```bash
    brew install danielgtaylor/restish/restish
    ```

=== "Go"

    ```bash
    go install github.com/danielgtaylor/restish@latest
    ```

### Load the configuration

The analyze command produces a `<name>.restish.json` file containing a single API entry. Merge it into your Restish configuration:

```bash
restish api edit < myapp-api.restish.json
```

Alternatively, copy the entry manually into `~/.config/restish/apis.json` under a key of your choice (the analyze command uses the output name).

### List available operations

Once the API is registered, Restish discovers all operations from the OpenAPI spec:

```bash
restish myapp-api --help
```

This lists every operation with its summary and HTTP method. Use tab completion to explore endpoints.

### Make a first call

Pick an operation from the list and call it:

```bash
restish myapp-api get-user-profile
```

Restish sends the request with the configured base URL and authentication, then displays the response with syntax highlighting.

## GraphQL APIs

GraphQL output is a `.graphql` SDL schema file. Since Restish only supports REST, GraphQL APIs use the auth helper script directly.

### Get a token

When the analyze command detects an authentication flow, it generates an auth helper (`<name>-auth.py`) that works independently of Restish. Run it to get a valid token:

```bash
python3 myapp-auth.py
```

The script prompts for credentials on first use, caches the token, and prints it to stdout. On subsequent runs it reuses the cached token until it expires.

### Use with curl

Pass the token in an Authorization header:

```bash
curl -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(python3 myapp-auth.py)" \
  -d '{"query": "{ viewer { name } }"}'
```

### Use with other GraphQL clients

Any client that accepts a token or custom headers can use the auth helper. The pattern is always the same: invoke `python3 <name>-auth.py` and capture its stdout as the token value.

## Authentication

### Interactive auth (auth helper script)

When the analyze command detects an authentication flow it can reproduce, it generates a Python auth helper script (`<name>-auth.py`). This script works for both REST and GraphQL APIs.

On first use, the script prompts you for credentials (username, password, OTP code, etc.) via the terminal. It performs the full authentication flow, caches the resulting token, and returns it.

On subsequent uses, the script reuses the cached token. When the token expires, it either refreshes it automatically (if a refresh endpoint was detected) or prompts you again.

For REST APIs using Restish, the Restish configuration references the script as an external tool (invoked with the `--restish` flag). For GraphQL and other use cases, run the script directly — it prints the token to stdout.

!!! info
    The auth script reads user input from `/dev/tty` rather than stdin, so it works correctly both when called directly and when invoked by Restish (which uses stdin to pipe the request JSON).

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
