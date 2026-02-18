"""Protocol detection from trace metadata."""

from __future__ import annotations

import json
import re
from typing import Any

from cli.capture.types import Trace, WsConnection
from cli.formats.capture_bundle import Header


def detect_trace_protocol(trace: Trace) -> str:
    """Detect the protocol used by a trace.

    Returns one of: "rest", "graphql", "grpc", "binary", "unknown"
    """
    url = trace.meta.request.url
    method = trace.meta.request.method.upper()
    content_type = _get_header(trace.meta.request.headers, "content-type")
    resp_content_type = _get_header(trace.meta.response.headers, "content-type")

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


def _is_graphql(url: str, method: str, body: bytes, content_type: str | None) -> bool:
    """Check if a request is a GraphQL request."""
    # URL-based detection
    if re.search(r"/graphql\b", url, re.IGNORECASE):
        return True

    # Body-based detection for POST requests
    if method == "POST" and body and content_type and "json" in content_type.lower():
        try:
            data: Any = json.loads(body)
            if isinstance(data, dict) and "query" in data:
                query_val = data["query"]  # pyright: ignore[reportUnknownVariableType]
                if isinstance(query_val, str) and re.search(
                    r"\b(query|mutation|subscription)\b", query_val
                ):
                    return True
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    # Query parameter detection for GET requests
    if method == "GET" and "query=" in url:
        return True

    return False


def _get_header(headers: list[Header], name: str) -> str | None:
    """Get a header value by name (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.name.lower() == name_lower:
            return h.value
    return None
