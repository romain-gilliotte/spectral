"""Protocol detection from trace metadata."""

from __future__ import annotations

import json
import re
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from cli.commands.capture.types import Trace, WsConnection
from cli.helpers.http import get_header

# Known non-REST protocols with human-readable display names.
PROTOCOL_DISPLAY_NAMES: dict[str, str] = {
    "graphql": "GraphQL",
    "grpc": "gRPC",
    "binary": "Binary",
    "soap": "SOAP",
    "sse": "Server-Sent Events",
    "ndjson": "NDJSON Streaming",
    "rsc": "React Server Components",
    "turbo-stream": "Hotwire Turbo Streams",
    "jsonapi": "JSON:API",
    "hal": "HAL",
    "odata": "OData",
    "restli": "Rest.li",
    "trpc": "tRPC",
    "socketio": "Socket.IO",
    "twirp": "Twirp",
    "signalr": "SignalR",
    "jsonrpc": "JSON-RPC",
    "xmlrpc": "XML-RPC",
}

# OData system query option prefixes.
_ODATA_QUERY_PARAMS = frozenset(
    {"$filter", "$select", "$expand", "$orderby", "$top", "$skip", "$count"}
)


def detect_trace_protocol(trace: Trace) -> str:
    """Detect the protocol used by a trace.

    Three-tier detection, ordered cheapest-first. Short-circuits at first match.

    Tier 1 — Headers/content-type (no body parse)
    Tier 2 — URL patterns (no body parse)
    Tier 3 — Body-based (JSON/XML parse)

    Returns a protocol string: "rest", "graphql", "grpc", "binary",
    "soap", "sse", "ndjson", "rsc", "turbo-stream", "jsonapi", "hal",
    "odata", "restli", "trpc", "socketio", "twirp", "signalr",
    "jsonrpc", "xmlrpc".
    """
    url = trace.meta.request.url
    method = trace.meta.request.method.upper()
    req_ct = get_header(trace.meta.request.headers, "content-type")
    resp_ct = get_header(trace.meta.response.headers, "content-type")
    req_ct_lower = req_ct.lower() if req_ct else ""
    resp_ct_lower = resp_ct.lower() if resp_ct else ""

    # ── Tier 1: Header / content-type checks ────────────────────────

    # gRPC
    if "grpc" in req_ct_lower or "grpc" in resp_ct_lower:
        return "grpc"

    # Binary (protobuf, octet-stream, msgpack, thrift)
    if req_ct_lower and any(
        t in req_ct_lower
        for t in ["protobuf", "octet-stream", "x-msgpack", "x-thrift"]
    ):
        return "binary"

    # SOAP
    if "soap+xml" in req_ct_lower or "soap+xml" in resp_ct_lower:
        return "soap"
    if get_header(trace.meta.request.headers, "soapaction") is not None:
        return "soap"

    # SSE
    if resp_ct_lower.startswith("text/event-stream"):
        return "sse"

    # NDJSON
    if "ndjson" in resp_ct_lower:
        return "ndjson"

    # React Server Components
    if resp_ct_lower.startswith("text/x-component"):
        return "rsc"
    if get_header(trace.meta.request.headers, "rsc") == "1":
        return "rsc"

    # Hotwire Turbo Streams
    if resp_ct_lower.startswith("text/vnd.turbo-stream.html"):
        return "turbo-stream"

    # JSON:API (content-type)
    if resp_ct_lower.startswith("application/vnd.api+json"):
        return "jsonapi"

    # HAL (content-type)
    if resp_ct_lower.startswith("application/hal+json"):
        return "hal"

    # OData (header)
    if (
        get_header(trace.meta.response.headers, "odata-version") is not None
        or get_header(trace.meta.response.headers, "odata-maxversion") is not None
    ):
        return "odata"

    # Rest.li (content-type or header)
    if "vnd.linkedin.normalized+json" in resp_ct_lower:
        return "restli"
    if get_header(trace.meta.request.headers, "x-restli-protocol-version") is not None:
        return "restli"

    # ── Tier 2: URL pattern checks ──────────────────────────────────

    parsed = urlparse(url)
    path = parsed.path

    # tRPC
    if "/trpc/" in path:
        return "trpc"

    # Socket.IO
    if "/socket.io/" in path:
        return "socketio"

    # Twirp — path segment starts with /twirp/
    if path.startswith("/twirp/") or "/twirp/" in path:
        return "twirp"

    # SignalR
    if "/signalr/" in path:
        return "signalr"

    # OData (URL query params)
    if parsed.query:
        qs = parse_qs(parsed.query, keep_blank_values=True)
        if any(k in _ODATA_QUERY_PARAMS for k in qs):
            return "odata"

    # ── Tier 3: Body-based checks ───────────────────────────────────

    # GraphQL (request body)
    if _is_graphql(method, trace.request_body, req_ct):
        return "graphql"

    # JSON-RPC (request body)
    if method == "POST" and trace.request_body and "json" in req_ct_lower:
        try:
            req_data: Any = json.loads(trace.request_body)
            if isinstance(req_data, dict) and "jsonrpc" in req_data:
                return "jsonrpc"
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    # XML-RPC (request body)
    if (
        method == "POST"
        and trace.request_body
        and "text/xml" in req_ct_lower
    ):
        body_start = trace.request_body[:200].lstrip()
        if body_start.startswith(b"<methodCall"):
            return "xmlrpc"

    # Response body checks (parse once, check multiple patterns)
    resp_body_json = _try_parse_response_json(trace.response_body, resp_ct_lower)
    if resp_body_json is not None and isinstance(resp_body_json, dict):
        resp_dict = cast(dict[str, Any], resp_body_json)

        # JSON:API (body) — "data" with objects having "type" + "id"
        if _is_jsonapi_body(resp_dict):
            return "jsonapi"

        # OData (body) — any @odata.* key
        if any(k.startswith("@odata.") for k in resp_dict):
            return "odata"

        # HAL (body) — "_links" dict with "self"
        links = resp_dict.get("_links")
        if isinstance(links, dict) and "self" in links:
            return "hal"

        # Rest.li (body) — "included" (list) + "data", entities have "$type"
        if _is_restli_body(resp_dict):
            return "restli"

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


# ── Private helpers ─────────────────────────────────────────────────


def _try_parse_response_json(
    body: bytes, resp_ct_lower: str
) -> Any | None:
    """Try to parse response body as JSON. Returns None on failure."""
    if not body or "json" not in resp_ct_lower:
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _is_jsonapi_body(data: dict[str, Any]) -> bool:
    """Check if a response body follows JSON:API structure."""
    d: Any = data.get("data")
    if d is None:
        return False
    # Single resource object
    if isinstance(d, dict):
        obj = cast(dict[str, Any], d)
        return isinstance(obj.get("type"), str) and "id" in obj
    # Array of resource objects
    if isinstance(d, list) and len(cast(list[Any], d)) > 0:
        first = cast(list[Any], d)[0]
        if isinstance(first, dict):
            obj = cast(dict[str, Any], first)
            return isinstance(obj.get("type"), str) and "id" in obj
    return False


def _is_restli_body(data: dict[str, Any]) -> bool:
    """Check if a response body follows Rest.li normalized format."""
    included: Any = data.get("included")
    if not isinstance(included, list) or "data" not in data:
        return False
    # Check that at least one entity has "$type"
    for entity in cast(list[Any], included):
        if isinstance(entity, dict) and "$type" in entity:
            return True
    return False


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


def _is_graphql(method: str, body: bytes, content_type: str | None) -> bool:
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
