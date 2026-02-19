"""Tests for Pydantic models in cli/formats/."""

from cli.formats.capture_bundle import (
    CaptureManifest,
    ContextMeta,
    ElementInfo,
    Header,
    PageInfo,
    RequestMeta,
    ResponseMeta,
    Timeline,
    TimelineEvent,
    TimingInfo,
    TraceMeta,
    ViewportInfo,
    WsConnectionMeta,
    WsMessageMeta,
)


class TestCaptureBundle:
    def test_header_model(self):
        h = Header(name="Content-Type", value="application/json")
        assert h.name == "Content-Type"
        assert h.value == "application/json"

    def test_manifest_roundtrip(self, sample_manifest: CaptureManifest):
        json_str = sample_manifest.model_dump_json()
        loaded = CaptureManifest.model_validate_json(json_str)
        assert loaded.capture_id == sample_manifest.capture_id
        assert loaded.app.name == "Test App"
        assert loaded.stats.trace_count == 3

    def test_trace_meta_roundtrip(self):
        trace = TraceMeta(
            id="t_0001",
            timestamp=1000000,
            request=RequestMeta(
                method="POST",
                url="https://api.example.com/data",
                headers=[Header(name="Authorization", value="Bearer tok")],
                body_file="t_0001_request.bin",
                body_size=42,
            ),
            response=ResponseMeta(
                status=200,
                status_text="OK",
                headers=[Header(name="Content-Type", value="application/json")],
                body_file="t_0001_response.bin",
                body_size=100,
            ),
            timing=TimingInfo(total_ms=150),
            context_refs=["c_0001"],
        )
        json_str = trace.model_dump_json()
        loaded = TraceMeta.model_validate_json(json_str)
        assert loaded.id == "t_0001"
        assert loaded.request.method == "POST"
        assert loaded.response.status == 200
        assert loaded.timing.total_ms == 150
        assert loaded.context_refs == ["c_0001"]

    def test_context_meta_roundtrip(self):
        ctx = ContextMeta(
            id="c_0001",
            timestamp=999000,
            action="click",
            element=ElementInfo(
                selector="button#submit",
                tag="BUTTON",
                text="Submit",
                attributes={"class": "btn-primary"},
                xpath="/html/body/button",
            ),
            page=PageInfo(url="https://example.com/form", title="Form"),
            viewport=ViewportInfo(width=1440, height=900),
        )
        json_str = ctx.model_dump_json()
        loaded = ContextMeta.model_validate_json(json_str)
        assert loaded.action == "click"
        assert loaded.element.text == "Submit"
        assert loaded.page.url == "https://example.com/form"

    def test_ws_connection_meta(self):
        ws = WsConnectionMeta(
            id="ws_0001",
            timestamp=1000,
            url="wss://realtime.example.com/ws",
            protocols=["graphql-ws"],
            message_count=10,
        )
        json_str = ws.model_dump_json()
        loaded = WsConnectionMeta.model_validate_json(json_str)
        assert loaded.protocols == ["graphql-ws"]

    def test_ws_message_meta(self):
        msg = WsMessageMeta(
            id="ws_0001_m001",
            connection_ref="ws_0001",
            timestamp=1001,
            direction="send",
            opcode="text",
            payload_file="ws_0001_m001.bin",
            payload_size=89,
        )
        json_str = msg.model_dump_json()
        loaded = WsMessageMeta.model_validate_json(json_str)
        assert loaded.direction == "send"
        assert loaded.payload_file == "ws_0001_m001.bin"

    def test_timeline_roundtrip(self):
        tl = Timeline(
            events=[
                TimelineEvent(timestamp=1000, type="context", ref="c_0001"),
                TimelineEvent(timestamp=2000, type="trace", ref="t_0001"),
            ]
        )
        json_str = tl.model_dump_json()
        loaded = Timeline.model_validate_json(json_str)
        assert len(loaded.events) == 2
        assert loaded.events[0].type == "context"

    def test_trace_meta_defaults(self):
        trace = TraceMeta(
            id="t_0001",
            timestamp=0,
            request=RequestMeta(method="GET", url="http://localhost"),
            response=ResponseMeta(status=200),
        )
        assert trace.type == "http"
        assert trace.timing.total_ms == 0
        assert trace.context_refs == []
        assert trace.initiator.type == "other"
