# Android apps

Spectral can capture traffic from Android apps by patching their APKs to trust user-installed CA certificates, then routing traffic through the MITM proxy.

## Prerequisites

- **adb** — Android SDK Platform Tools, for communicating with the device
- **java** — JDK, for signing patched APKs
- A connected Android device or emulator with USB debugging enabled

## Workflow overview

The full workflow is: find the package, pull the APK, patch it, install it, push the certificate, then capture traffic through the proxy. Each step has a dedicated CLI command.

## Find the package

Search for a package by name:

```bash
uv run spectral android list spotify
```

This lists matching package names installed on the connected device (e.g., `com.spotify.music`).

## Pull the APK

Download the APK from the device:

```bash
uv run spectral android pull com.spotify.music
```

For single APKs this produces `com.spotify.music.apk`. Some apps use split APKs — these are downloaded into a directory named `com.spotify.music/`.

Use `-o` to specify a custom output path.

## Patch the APK

On Android 7 and later, apps only trust system CA certificates by default and ignore user-installed ones. The patch command modifies the APK to add a network security configuration that trusts user CAs, then re-signs it:

```bash
uv run spectral android patch com.spotify.music.apk
```

This produces `com.spotify.music-patched.apk` (or a `-patched/` directory for split APKs).

!!! note
    Patching requires `apktool` (for decompiling/recompiling) and `java` (for signing). The patched APK is signed with a debug key, so it cannot be installed alongside the original — uninstall the original first.

## Install the patched APK

```bash
uv run spectral android install com.spotify.music-patched.apk
```

For split APKs, pass the directory:

```bash
uv run spectral android install com.spotify.music-patched/
```

## Push the certificate

Push the mitmproxy CA certificate to the device:

```bash
uv run spectral android cert
```

This copies `~/.mitmproxy/mitmproxy-ca-cert.pem` to the device's SD card. If you haven't run mitmproxy before, run it once to generate the certificate, then retry.

After pushing, install the certificate on the device: **Settings > Security > Install from storage > CA certificate**, then select the uploaded file.

## Capture traffic

Configure the device to use the proxy. Go to **Settings > Wi-Fi**, long-press your network, edit the proxy settings to point to your machine's IP address on port 8080.

Then start the proxy as usual:

```bash
uv run spectral capture proxy -d "*.spotify.com" -o spotify-capture.zip
```

Use the app on the device. The proxy captures all traffic from the patched app. Press `Ctrl+C` to stop and export the bundle.
