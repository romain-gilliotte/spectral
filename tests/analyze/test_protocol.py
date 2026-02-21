"""Tests for protocol detection."""

import json

from cli.commands.analyze.protocol import detect_trace_protocol, detect_ws_protocol
from cli.formats.capture_bundle import Header
from tests.conftest import make_trace, make_ws_connection, make_ws_message


class TestDetectTraceProtocol:
    def test_rest_default(self):
        trace = make_trace("t_0001", "GET", "https://api.example.com/users", 200, 1000)
        assert detect_trace_protocol(trace) == "rest"

    def test_graphql_url_without_body_is_rest(self):
        """A POST to /graphql without a JSON body is not classified as GraphQL."""
        trace = make_trace(
            "t_0001", "POST", "https://api.example.com/graphql", 200, 1000
        )
        assert detect_trace_protocol(trace) == "rest"

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

    def test_graphql_get_with_query_param_is_rest(self):
        """GET requests are not classified as GraphQL (body-only detection)."""
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/graphql?query={users{id}}",
            200,
            1000,
        )
        assert detect_trace_protocol(trace) == "rest"

    def test_graphql_persisted_query(self):
        """A persisted query (extensions.persistedQuery, no query field) is GraphQL."""
        body = json.dumps({
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "abc123",
                }
            }
        }).encode()
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

    def test_graphql_batch(self):
        """A batch of GraphQL queries is detected as GraphQL."""
        body = json.dumps([
            {"query": "query { users { id } }"},
            {"query": "query { posts { title } }"},
        ]).encode()
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

    def test_graphql_shorthand_query(self):
        """A shorthand query (no keyword, just braces) is detected as GraphQL."""
        body = json.dumps({"query": "{ users { id } }"}).encode()
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

    def test_graphql_named_operation(self):
        """A named operation without query text (Reddit-style) is GraphQL."""
        body = json.dumps({
            "operation": "UserCommunityAchievements",
            "variables": {"username": "testuser", "subredditId": "t5_abc"},
        }).encode()
        trace = make_trace(
            "t_0001",
            "POST",
            "https://www.reddit.com/svc/shreddit/graphql",
            200,
            1000,
            request_body=body,
            request_headers=[Header(name="Content-Type", value="application/json")],
        )
        assert detect_trace_protocol(trace) == "graphql"

    def test_graphql_operation_name_with_variables(self):
        """operationName + variables (without query) is GraphQL."""
        body = json.dumps({
            "operationName": "GetPlaylist",
            "variables": {"id": "123"},
        }).encode()
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/gql",
            200,
            1000,
            request_body=body,
            request_headers=[Header(name="Content-Type", value="application/json")],
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

    # ── Tier 1: Header-based detection ──────────────────────────────

    def test_soap_by_content_type(self):
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/ws",
            200,
            1000,
            request_headers=[
                Header(name="Content-Type", value="application/soap+xml; charset=utf-8")
            ],
        )
        assert detect_trace_protocol(trace) == "soap"

    def test_soap_by_response_content_type(self):
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/ws",
            200,
            1000,
            request_headers=[Header(name="Content-Type", value="text/xml")],
            response_headers=[
                Header(name="Content-Type", value="application/soap+xml")
            ],
        )
        assert detect_trace_protocol(trace) == "soap"

    def test_soap_by_soapaction_header(self):
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/ws",
            200,
            1000,
            request_headers=[
                Header(name="Content-Type", value="text/xml"),
                Header(name="SOAPAction", value="urn:GetUser"),
            ],
        )
        assert detect_trace_protocol(trace) == "soap"

    def test_sse_by_response_content_type(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/events",
            200,
            1000,
            response_headers=[
                Header(name="Content-Type", value="text/event-stream")
            ],
        )
        assert detect_trace_protocol(trace) == "sse"

    def test_ndjson_by_response_content_type(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/stream",
            200,
            1000,
            response_headers=[
                Header(name="Content-Type", value="application/x-ndjson")
            ],
        )
        assert detect_trace_protocol(trace) == "ndjson"

    def test_rsc_by_response_content_type(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://app.example.com/page",
            200,
            1000,
            response_headers=[
                Header(name="Content-Type", value="text/x-component")
            ],
        )
        assert detect_trace_protocol(trace) == "rsc"

    def test_rsc_by_request_header(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://app.example.com/page",
            200,
            1000,
            request_headers=[Header(name="RSC", value="1")],
        )
        assert detect_trace_protocol(trace) == "rsc"

    def test_turbo_stream_by_response_content_type(self):
        trace = make_trace(
            "t_0001",
            "POST",
            "https://app.example.com/messages",
            200,
            1000,
            response_headers=[
                Header(
                    name="Content-Type",
                    value="text/vnd.turbo-stream.html; charset=utf-8",
                )
            ],
        )
        assert detect_trace_protocol(trace) == "turbo-stream"

    def test_jsonapi_by_response_content_type(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/articles",
            200,
            1000,
            response_headers=[
                Header(name="Content-Type", value="application/vnd.api+json")
            ],
        )
        assert detect_trace_protocol(trace) == "jsonapi"

    def test_hal_by_response_content_type(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/orders",
            200,
            1000,
            response_headers=[
                Header(name="Content-Type", value="application/hal+json")
            ],
        )
        assert detect_trace_protocol(trace) == "hal"

    def test_odata_by_response_header(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/Products",
            200,
            1000,
            response_headers=[
                Header(name="Content-Type", value="application/json"),
                Header(name="OData-Version", value="4.0"),
            ],
        )
        assert detect_trace_protocol(trace) == "odata"

    def test_odata_by_maxversion_header(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/Products",
            200,
            1000,
            response_headers=[
                Header(name="Content-Type", value="application/json"),
                Header(name="OData-MaxVersion", value="4.0"),
            ],
        )
        assert detect_trace_protocol(trace) == "odata"

    def test_restli_by_response_content_type(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://www.linkedin.com/voyager/api/feed",
            200,
            1000,
            response_headers=[
                Header(
                    name="Content-Type",
                    value="application/vnd.linkedin.normalized+json+2.1",
                )
            ],
        )
        assert detect_trace_protocol(trace) == "restli"

    def test_restli_by_request_header(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://www.linkedin.com/voyager/api/feed",
            200,
            1000,
            request_headers=[
                Header(name="X-RestLi-Protocol-Version", value="2.0.0")
            ],
        )
        assert detect_trace_protocol(trace) == "restli"

    # ── Tier 2: URL-based detection ─────────────────────────────────

    def test_trpc_by_url(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/trpc/user.getById?input=%7B%22id%22%3A1%7D",
            200,
            1000,
        )
        assert detect_trace_protocol(trace) == "trpc"

    def test_trpc_in_query_param_is_not_trpc(self):
        """'trpc' in a query param value should not trigger tRPC detection."""
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/search?q=trpc+guide",
            200,
            1000,
        )
        assert detect_trace_protocol(trace) == "rest"

    def test_socketio_by_url(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://app.example.com/socket.io/?EIO=4&transport=polling",
            200,
            1000,
        )
        assert detect_trace_protocol(trace) == "socketio"

    def test_twirp_by_url(self):
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/twirp/example.v1.UserService/GetUser",
            200,
            1000,
        )
        assert detect_trace_protocol(trace) == "twirp"

    def test_signalr_by_url(self):
        trace = make_trace(
            "t_0001",
            "POST",
            "https://app.example.com/signalr/negotiate?negotiateVersion=1",
            200,
            1000,
        )
        assert detect_trace_protocol(trace) == "signalr"

    def test_odata_by_query_params(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/Products?$filter=Price gt 10&$select=Name,Price",
            200,
            1000,
        )
        assert detect_trace_protocol(trace) == "odata"

    def test_odata_top_skip_query_params(self):
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/Products?$top=10&$skip=20",
            200,
            1000,
        )
        assert detect_trace_protocol(trace) == "odata"

    def test_dollar_sign_in_query_not_odata(self):
        """A query param starting with $ but not an OData keyword stays REST."""
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/search?$custom=value",
            200,
            1000,
        )
        assert detect_trace_protocol(trace) == "rest"

    # ── Tier 3: Body-based detection ────────────────────────────────

    def test_jsonrpc_by_request_body(self):
        body = json.dumps(
            {"jsonrpc": "2.0", "method": "user.get", "params": {"id": 1}, "id": 1}
        ).encode()
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/rpc",
            200,
            1000,
            request_body=body,
            request_headers=[Header(name="Content-Type", value="application/json")],
        )
        assert detect_trace_protocol(trace) == "jsonrpc"

    def test_xmlrpc_by_request_body(self):
        body = b"<methodCall><methodName>getUser</methodName></methodCall>"
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/xmlrpc",
            200,
            1000,
            request_body=body,
            request_headers=[Header(name="Content-Type", value="text/xml")],
        )
        assert detect_trace_protocol(trace) == "xmlrpc"

    def test_text_xml_without_method_call_is_rest(self):
        """text/xml without <methodCall body stays REST."""
        body = b"<data><value>42</value></data>"
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/xml",
            200,
            1000,
            request_body=body,
            request_headers=[Header(name="Content-Type", value="text/xml")],
        )
        assert detect_trace_protocol(trace) == "rest"

    def test_jsonapi_by_response_body(self):
        resp = json.dumps({
            "data": {"type": "articles", "id": "1", "attributes": {"title": "Foo"}}
        }).encode()
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/articles/1",
            200,
            1000,
            response_body=resp,
            response_headers=[
                Header(name="Content-Type", value="application/json")
            ],
        )
        assert detect_trace_protocol(trace) == "jsonapi"

    def test_jsonapi_by_response_body_array(self):
        resp = json.dumps({
            "data": [
                {"type": "articles", "id": "1", "attributes": {"title": "Foo"}},
                {"type": "articles", "id": "2", "attributes": {"title": "Bar"}},
            ]
        }).encode()
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/articles",
            200,
            1000,
            response_body=resp,
            response_headers=[
                Header(name="Content-Type", value="application/json")
            ],
        )
        assert detect_trace_protocol(trace) == "jsonapi"

    def test_jsonapi_body_without_type_is_rest(self):
        """A response with 'data' but no 'type'+'id' objects stays REST."""
        resp = json.dumps({"data": [{"name": "foo"}, {"name": "bar"}]}).encode()
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/data",
            200,
            1000,
            response_body=resp,
            response_headers=[
                Header(name="Content-Type", value="application/json")
            ],
        )
        assert detect_trace_protocol(trace) == "rest"

    def test_odata_by_response_body(self):
        resp = json.dumps({
            "@odata.context": "https://api.example.com/$metadata#Products",
            "value": [{"Name": "Widget", "Price": 9.99}],
        }).encode()
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/Products",
            200,
            1000,
            response_body=resp,
            response_headers=[
                Header(name="Content-Type", value="application/json")
            ],
        )
        assert detect_trace_protocol(trace) == "odata"

    def test_hal_by_response_body(self):
        resp = json.dumps({
            "_links": {"self": {"href": "/orders/123"}},
            "total": 42.5,
        }).encode()
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/orders/123",
            200,
            1000,
            response_body=resp,
            response_headers=[
                Header(name="Content-Type", value="application/json")
            ],
        )
        assert detect_trace_protocol(trace) == "hal"

    def test_hal_body_without_self_is_rest(self):
        """_links without 'self' key stays REST."""
        resp = json.dumps({
            "_links": {"next": {"href": "/orders?page=2"}},
            "items": [],
        }).encode()
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/orders",
            200,
            1000,
            response_body=resp,
            response_headers=[
                Header(name="Content-Type", value="application/json")
            ],
        )
        assert detect_trace_protocol(trace) == "rest"

    def test_restli_by_response_body(self):
        resp = json.dumps({
            "data": {"some": "data"},
            "included": [
                {"$type": "com.linkedin.voyager.feed.Update", "id": "urn:li:activity:123"}
            ],
        }).encode()
        trace = make_trace(
            "t_0001",
            "GET",
            "https://www.linkedin.com/voyager/api/feed",
            200,
            1000,
            response_body=resp,
            response_headers=[
                Header(name="Content-Type", value="application/json")
            ],
        )
        assert detect_trace_protocol(trace) == "restli"

    def test_restli_body_without_dollar_type_is_rest(self):
        """'included' + 'data' without '$type' entities stays REST."""
        resp = json.dumps({
            "data": {"some": "data"},
            "included": [{"id": "123", "name": "foo"}],
        }).encode()
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/feed",
            200,
            1000,
            response_body=resp,
            response_headers=[
                Header(name="Content-Type", value="application/json")
            ],
        )
        assert detect_trace_protocol(trace) == "rest"

    # ── Tier priority tests ─────────────────────────────────────────

    def test_grpc_takes_priority_over_body_checks(self):
        """gRPC content-type wins even with a JSON body that looks like GraphQL."""
        body = json.dumps({"query": "query { users { id } }"}).encode()
        trace = make_trace(
            "t_0001",
            "POST",
            "https://api.example.com/service",
            200,
            1000,
            request_body=body,
            request_headers=[
                Header(name="Content-Type", value="application/grpc+json")
            ],
        )
        assert detect_trace_protocol(trace) == "grpc"

    def test_header_detection_beats_url_pattern(self):
        """SSE content-type wins even with /trpc/ in the URL."""
        trace = make_trace(
            "t_0001",
            "GET",
            "https://api.example.com/trpc/updates",
            200,
            1000,
            response_headers=[
                Header(name="Content-Type", value="text/event-stream")
            ],
        )
        assert detect_trace_protocol(trace) == "sse"


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
