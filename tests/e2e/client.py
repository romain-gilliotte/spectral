"""Client script that authenticates and exercises the test server.

Importable (``from tests.e2e.client import run_client``) or runnable standalone::

    python tests/e2e/client.py --base-url http://127.0.0.1:5100 --proxy-url http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import sys

import requests


def run_client(base_url: str, proxy_url: str | None = None) -> None:
    """Authenticate against the test server and make a few API calls."""
    session = requests.Session()
    if proxy_url:
        session.proxies = {"http": proxy_url, "https": proxy_url}

    # 1. Authenticate
    resp = session.post(
        f"{base_url}/oauth/token",
        json={"username": "testuser", "password": "testpass"},
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    session.headers["Authorization"] = f"Bearer {token}"

    # 2. List products
    resp = session.get(f"{base_url}/api/products")
    resp.raise_for_status()

    # 3. Get a single product
    resp = session.get(f"{base_url}/api/products/1")
    resp.raise_for_status()

    # 4. Create an order
    resp = session.post(
        f"{base_url}/api/orders",
        json={"product_id": 1, "quantity": 2},
    )
    resp.raise_for_status()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="E2E test client for Spectral")
    parser.add_argument("--base-url", default="http://127.0.0.1:5100")
    parser.add_argument("--proxy-url", default=None)
    args = parser.parse_args()
    run_client(args.base_url, args.proxy_url)
    print("All requests completed successfully.", file=sys.stderr)
