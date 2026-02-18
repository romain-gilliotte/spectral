"""Tests for protocol detection."""

import json

from cli.commands.analyze.protocol import detect_trace_protocol, detect_ws_protocol
from cli.formats.capture_bundle import Header
from tests.conftest import make_trace, make_ws_connection, make_ws_message


class TestDetectTraceProtocol:
    def test_rest_default(self):
        trace = make_trace("t_0001", "GET", "https://api.example.com/users", 200, 1000)
        assert detect_trace_protocol(trace) == "rest"

    def test_graphql_by_url(self):
        trace = make_trace(
            "t_0001", "POST", "https://api.example.com/graphql", 200, 1000
        )
        assert detect_trace_protocol(trace) == "graphql"

    def test_graphql_by_body(self):
        body = json.dumps({"query": "query { users { id name } }"}).encode()
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/api",
            200,
            1000,
            request_body=body,
            request_headers=[Header(name="Content-Type", value="application/json")],
        )
        assert detect_trace_protocol(trace) == "graphql"

    def test_graphql_mutation_by_body(self):
        body = json.dumps(
            {"query": 'mutation { createUser(name: "test") { id } }'}
        ).encode()
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/api",
            200,
            1000,
            request_body=body,
            request_headers=[Header(name="Content-Type", value="application/json")],
        )
        assert detect_trace_protocol(trace) == "graphql"

    def test_grpc_by_content_type(self):
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/service",
            200,
            1000,
            request_headers=[Header(name="Content-Type", value="application/grpc")],
        )
        assert detect_trace_protocol(trace) == "grpc"

    def test_binary_by_content_type(self):
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/data",
            200,
            1000,
            request_headers=[
                Header(name="Content-Type", value="application/octet-stream")
            ],
        )
        assert detect_trace_protocol(trace) == "binary"

    def test_protobuf_detected_as_binary(self):
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/data",
            200,
            1000,
            request_headers=[
                Header(name="Content-Type", value="application/x-protobuf")
            ],
        )
        assert detect_trace_protocol(trace) == "binary"

    def test_graphql_get_with_query_param(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/graphql?query={users{id}}",
            200,
            1000,
        )
        assert detect_trace_protocol(trace) == "graphql"

    def test_non_graphql_json_body(self):
        body = json.dumps({"name": "test", "value": 42}).encode()
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/data",
            200,
            1000,
            request_body=body,
            request_headers=[Header(name="Content-Type", value="application/json")],
        )
        assert detect_trace_protocol(trace) == "rest"


class TestDetectWsProtocol:
    def test_graphql_ws_by_protocol(self):
        ws = make_ws_connection(
            "ws_0001", "wss://example.com/ws", 1000, protocols=["graphql-ws"]
        )
        assert detect_ws_protocol(ws) == "graphql-ws"

    def test_graphql_ws_by_message(self):
        msg = make_ws_message(
            "ws_0001_m001",
            "ws_0001",
            1001,
            "send",
            json.dumps({"type": "connection_init"}).encode(),
        )
        ws = make_ws_connection("ws_0001", "wss://example.com/ws", 1000, messages=[msg])
        assert detect_ws_protocol(ws) == "graphql-ws"

    def test_json_rpc_by_message(self):
        msg = make_ws_message(
            "ws_0001_m001",
            "ws_0001",
            1001,
            "send",
            json.dumps({"jsonrpc": "2.0", "method": "test", "id": 1}).encode(),
        )
        ws = make_ws_connection("ws_0001", "wss://example.com/ws", 1000, messages=[msg])
        assert detect_ws_protocol(ws) == "json-rpc"

    def test_plain_json_by_message(self):
        msg = make_ws_message(
            "ws_0001_m001",
            "ws_0001",
            1001,
            "send",
            json.dumps({"foo": "bar"}).encode(),
        )
        ws = make_ws_connection("ws_0001", "wss://example.com/ws", 1000, messages=[msg])
        assert detect_ws_protocol(ws) == "plain-json"

    def test_binary_protocol(self):
        from cli.commands.capture.types import WsMessage
        from cli.formats.capture_bundle import WsMessageMeta

        msg = WsMessage(
            meta=WsMessageMeta(
                id="ws_0001_m001",
                connection_ref="ws_0001",
                timestamp=1001,
                direction="send",
                opcode="binary",
                payload_size=10,
            ),
            payload=b"\x00\x01\x02",
        )
        ws = make_ws_connection("ws_0001", "wss://example.com/ws", 1000, messages=[msg])
        assert detect_ws_protocol(ws) == "binary"

    def test_unknown_protocol_no_messages(self):
        ws = make_ws_connection("ws_0001", "wss://example.com/ws", 1000)
        assert detect_ws_protocol(ws) == "unknown"

    def test_graphql_subscribe_message(self):
        msg = make_ws_message(
            "ws_0001_m001",
            "ws_0001",
            1001,
            "send",
            json.dumps(
                {
                    "type": "subscribe",
                    "id": "1",
                    "payload": {"query": "subscription { data }"},
                }
            ).encode(),
        )
        ws = make_ws_connection("ws_0001", "wss://example.com/ws", 1000, messages=[msg])
        assert detect_ws_protocol(ws) == "graphql-ws"
