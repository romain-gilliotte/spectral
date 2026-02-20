# Certificate setup

The MITM proxy intercepts HTTPS by generating certificates signed by the mitmproxy CA. For interception to work, this CA must be trusted by the system or application making the requests.

## Generate the CA certificate

Run mitmproxy once to generate its CA:

```bash
mitmproxy
```

Then quit (`q`, `y`). The CA files are created in `~/.mitmproxy/`. The file you need to install is `mitmproxy-ca-cert.pem`.

## macOS

Add the certificate to the system keychain and mark it as trusted:

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/.mitmproxy/mitmproxy-ca-cert.pem
```

Alternatively, open Keychain Access, import the certificate, double-click it, expand "Trust", and set "When using this certificate" to "Always Trust".

## Linux (Debian/Ubuntu)

Copy the certificate and update the trust store:

```bash
sudo cp ~/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt
sudo update-ca-certificates
```

!!! note
    The file must have a `.crt` extension for `update-ca-certificates` to pick it up.

## Linux (Fedora/RHEL)

```bash
sudo cp ~/.mitmproxy/mitmproxy-ca-cert.pem /etc/pki/ca-trust/source/anchors/mitmproxy.pem
sudo update-ca-trust
```

## Firefox

Firefox uses its own certificate store and ignores the system trust store. To add the certificate in Firefox:

1. Open **Settings > Privacy & Security > Certificates > View Certificates**
2. Go to the **Authorities** tab
3. Click **Import** and select `~/.mitmproxy/mitmproxy-ca-cert.pem`
4. Check "Trust this CA to identify websites"

## Android

For Android apps, use the Spectral CLI to push the certificate:

```bash
uv run spectral android cert
```

Then install it on the device: **Settings > Security > Install from storage > CA certificate**, and select the uploaded file.

!!! warning
    On Android 7+, user-installed CA certificates are only trusted by apps that explicitly opt in via their network security configuration. The `spectral android patch` command modifies apps to trust user CAs. See [Android apps](android.md) for the full workflow.

## Verification

After installing the certificate, verify that the proxy can intercept HTTPS:

```bash
uv run spectral capture proxy &
HTTPS_PROXY=http://127.0.0.1:8080 curl -I https://example.com
```

If the `curl` command succeeds without certificate errors, the setup is correct. If you see a certificate verification error, the CA is not properly trusted by the system or application.
