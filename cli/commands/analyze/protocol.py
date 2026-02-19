"""Protocol detection from trace metadata."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from cli.commands.capture.types import Trace, WsConnection
from cli.helpers.http import get_header


def detect_trace_protocol(trace: Trace) -> str:
    """Detect the protocol used by a trace.

    Returns one of: "rest", "graphql", "grpc", "binary", "unknown"
    """
    url = trace.meta.request.url
    method = trace.meta.request.method.upper()
    content_type = get_header(trace.meta.request.headers, "content-type")
    resp_content_type = get_header(trace.meta.response.headers, "content-type")

    # gRPC detection
    if content_type and "grpc" in content_type.lower():
        return "grpc"
    if resp_content_type and "grpc" in resp_content_type.lower():
        return "grpc"

    # GraphQL detection
    if _is_graphql(url, method, trace.request_body, content_type):
        return "graphql"

    # Binary protocol detection
    if content_type and any(
        t in content_type.lower()
        for t in ["protobuf", "octet-stream", "x-msgpack", "x-thrift"]
    ):
        return "binary"

    # Default: REST
    return "rest"


def detect_ws_protocol(ws_conn: WsConnection) -> str:
    """Detect the sub-protocol used by a WebSocket connection.

    Returns one of: "graphql-ws", "json-rpc", "plain-json", "binary", "unknown"
    """
    # Check declared sub-protocols
    for proto in ws_conn.meta.protocols:
        if "graphql" in proto.lower():
            return "graphql-ws"

    # Inspect message payloads
    for msg in ws_conn.messages:
        if msg.meta.opcode == "binary":
            return "binary"
        if msg.payload:
            try:
                data = json.loads(msg.payload)
                if isinstance(data, dict):
                    # GraphQL-WS protocol
                    if data.get("type") in (  # pyright: ignore[reportUnknownMemberType]
                        "connection_init",
                        "subscribe",
                        "next",
                        "complete",
                        "connection_ack",
                    ):
                        return "graphql-ws"
                    # JSON-RPC
                    if "jsonrpc" in data or ("method" in data and "id" in data):
                        return "json-rpc"
                    return "plain-json"
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

    return "unknown"


def _is_graphql_item(data: dict[str, Any]) -> bool:
    """Check if a single JSON object looks like a GraphQL request.

    Matches three shapes:
    - Normal query: ``{"query": "query { ... }", ...}``
    - Persisted query (hash): ``{"extensions": {"persistedQuery": {...}}, ...}``
    - Named operation (no query text): ``{"operation": "FetchUsers", "variables": {...}}``
    """
    query_val = data.get("query")
    if isinstance(query_val, str) and re.search(
        r"\b(query|mutation|subscription)\b|\{", query_val
    ):
        return True
    extensions = data.get("extensions")
    if isinstance(extensions, dict) and "persistedQuery" in extensions:
        return True
    # Named operation without query text (e.g. Reddit): server-side registered
    # queries identified by name only.
    if (
        isinstance(data.get("operationName"), str)
        or isinstance(data.get("operation"), str)
    ) and isinstance(data.get("variables"), dict):
        return True
    return False


def _is_graphql(url: str, method: str, body: bytes, content_type: str | None) -> bool:
    """Check if a request is a GraphQL request based on the JSON body."""
    if method != "POST" or not body or not content_type:
        return False
    if "json" not in content_type.lower():
        return False

    try:
        data: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False

    if isinstance(data, dict):
        return _is_graphql_item(cast(dict[str, Any], data))
    if isinstance(data, list):
        return any(
            isinstance(item, dict) and _is_graphql_item(cast(dict[str, Any], item))
            for item in cast(list[Any], data)
        )
    return False
