"""Minimal Flask server for E2E testing.

OAuth2 password grant + 3 business endpoints (products, orders).
Runnable standalone: ``python tests/e2e/server.py [port]``
"""

from __future__ import annotations

import sys
from typing import Any
import uuid

from flask import Flask, jsonify, request

app = Flask(__name__)

_VALID_CREDENTIALS = {"username": "testuser", "password": "testpass"}

_PRODUCTS = [
    {"id": 1, "name": "Widget", "price": 9.99, "category": "electronics"},
    {"id": 2, "name": "Gadget", "price": 19.99, "category": "electronics"},
    {"id": 3, "name": "Doohickey", "price": 4.99, "category": "accessories"},
]


def _check_auth() -> tuple[dict[str, str], int] | None:
    """Return an error response tuple if auth is invalid, else None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer test-token-"):
        return {"error": "unauthorized"}, 401
    return None


# --------------------------------------------------------------------------- #
# OAuth2 password grant
# --------------------------------------------------------------------------- #

@app.post("/oauth/token")
def token():  # type: ignore[return-value]
    data: dict[str, Any] = request.get_json(silent=True) or {}
    username: str = data.get("username", "")
    password: str = data.get("password", "")
    if username == _VALID_CREDENTIALS["username"] and password == _VALID_CREDENTIALS["password"]:
        return jsonify(
            {
                "access_token": f"test-token-{username}",
                "token_type": "bearer",
                "expires_in": 3600,
            }
        )
    return jsonify({"error": "invalid_credentials"}), 401


# --------------------------------------------------------------------------- #
# Business endpoints
# --------------------------------------------------------------------------- #

@app.get("/api/products")
def list_products():
    err = _check_auth()
    if err:
        return jsonify(err[0]), err[1]
    category = request.args.get("category")
    products = _PRODUCTS
    if category:
        products = [p for p in products if p["category"] == category]
    return jsonify(products)


@app.get("/api/products/<int:product_id>")
def get_product(product_id: int):
    err = _check_auth()
    if err:
        return jsonify(err[0]), err[1]
    for p in _PRODUCTS:
        if p["id"] == product_id:
            return jsonify(p)
    return jsonify({"error": "not_found"}), 404


@app.post("/api/orders")
def create_order():
    err = _check_auth()
    if err:
        return jsonify(err[0]), err[1]
    data: dict[str, Any] = request.get_json(silent=True) or {}
    product_id: int | None = data.get("product_id")
    quantity: int = data.get("quantity", 1)
    product = next((p for p in _PRODUCTS if p["id"] == product_id), None)
    if not product:
        return jsonify({"error": "product_not_found"}), 404
    return jsonify(
        {
            "order_id": f"ord-{uuid.uuid4().hex[:8]}",
            "product_id": product_id,
            "quantity": quantity,
            "total": round(float(product["price"]) * quantity, 2),
            "status": "created",
        }
    ), 201


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5100
    app.run(host="127.0.0.1", port=port)
