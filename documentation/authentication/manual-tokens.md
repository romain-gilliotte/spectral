# Manual token management

When the generated auth script doesn't work or isn't available, Spectral provides manual alternatives to get tokens into managed storage.

## Extracting tokens from traces

The `spectral auth extract` command scans all captured traces for auth headers and writes them directly to `token.json`. It tries a fast path first (looks for `Authorization` headers directly), falling back to the LLM to identify other auth headers if needed.

This is the quickest way to get a working token when you already have authenticated traffic in your captures. Unlike `auth analyze`, it does not produce a reusable script — the extracted tokens will expire and cannot be refreshed automatically.

## Manual header injection

If you already have a token from another source, inject it directly:

```bash
spectral auth set myapp -H "Authorization: Bearer eyJ..."
```

For cookie-based authentication:

```bash
spectral auth set myapp -c "session=abc123"
```

Multiple headers and cookies can be combined:

```bash
spectral auth set myapp -H "Authorization: Bearer eyJ..." -c "csrf=xyz"
```

If neither `--header` nor `--cookie` is given, the command prompts for a token interactively and stores it as `Authorization: Bearer <token>`.

## Clearing credentials

To remove stored credentials for an app:

```bash
spectral auth logout myapp
```

This deletes `token.json` from managed storage.
