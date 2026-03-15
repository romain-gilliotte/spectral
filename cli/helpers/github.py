"""GitHub App Device Flow and Contents API helpers for catalog operations."""

from __future__ import annotations

import time
from typing import Any

import requests

# GitHub App client ID for Spectral Catalog (Device Flow)
GITHUB_CLIENT_ID = "Iv23lifHAAA7qJEURvLI"

_DEVICE_CODE_URL = "https://github.com/login/device/code"
_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
_API_BASE = "https://api.github.com"


class DeviceFlowError(Exception):
    """Raised when the GitHub Device Flow fails."""


class DeviceFlowPending:
    """Intermediate state while waiting for user authorization."""

    def __init__(self, device_code: str, user_code: str, verification_uri: str, interval: int) -> None:
        self.device_code = device_code
        self.user_code = user_code
        self.verification_uri = verification_uri
        self.interval = interval


def start_device_flow() -> DeviceFlowPending:
    """Initiate the GitHub Device Flow. Returns codes for user interaction."""
    resp = requests.post(
        _DEVICE_CODE_URL,
        data={"client_id": GITHUB_CLIENT_ID},
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return DeviceFlowPending(
        device_code=data["device_code"],
        user_code=data["user_code"],
        verification_uri=data["verification_uri"],
        interval=data.get("interval", 5),
    )


def poll_for_token(pending: DeviceFlowPending) -> str:
    """Poll GitHub until the user authorizes (or timeout). Returns access_token."""
    while True:
        time.sleep(pending.interval)
        resp = requests.post(
            _ACCESS_TOKEN_URL,
            data={
                "client_id": GITHUB_CLIENT_ID,
                "device_code": pending.device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if "access_token" in data:
            return data["access_token"]

        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            pending.interval += 5
            continue
        if error == "expired_token":
            raise DeviceFlowError("Device code expired. Please try again.")
        if error == "access_denied":
            raise DeviceFlowError("Authorization was denied by the user.")
        raise DeviceFlowError(f"Unexpected error: {error}")


def get_github_user(access_token: str) -> dict[str, Any]:
    """Fetch the authenticated user profile from GitHub."""
    resp = requests.get(
        f"{_API_BASE}/user",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def download_directory(username: str, app_name: str, repo: str = "spectral-mcp/spectral-tools") -> list[dict[str, Any]]:
    """Download all files from a catalog directory via the GitHub Contents API.

    Returns a list of dicts with ``name`` and ``content`` (decoded text) keys.
    """
    url = f"{_API_BASE}/repos/{repo}/contents/{username}/{app_name}"
    resp = requests.get(
        url,
        headers={"Accept": "application/vnd.github+json"},
        timeout=15,
    )
    resp.raise_for_status()
    entries = resp.json()

    files: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("type") != "file" or not entry["name"].endswith(".json"):
            continue
        file_resp = requests.get(
            entry["download_url"],
            timeout=15,
        )
        file_resp.raise_for_status()
        files.append({"name": entry["name"], "content": file_resp.text})
    return files
