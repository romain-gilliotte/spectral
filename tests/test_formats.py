"""Tests for Pydantic models in cli/formats/."""

from cli.formats.api_spec import (
    ApiSpec,
    AuthInfo,
    BusinessContext,
    EndpointSpec,
    LoginEndpointConfig,
    ParameterSpec,
    Protocols,
    RefreshEndpointConfig,
    RequestSpec,
    ResponseSpec,
    RestProtocol,
    UiTrigger,
    WsConnectionSpec,
    WsMessageSpec,
)
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


class TestApiSpec:
    def test_api_spec_roundtrip(self):
        spec = ApiSpec(
            name="Test API",
            discovery_date="2026-02-13T15:30:00Z",
            source_captures=["test.zip"],
            business_context=BusinessContext(
                domain="Testing", description="A test API"
            ),
            auth=AuthInfo(
                type="bearer_token", token_header="Authorization", token_prefix="Bearer"
            ),
            protocols=Protocols(
                rest=RestProtocol(
                    base_url="https://api.example.com",
                    endpoints=[
                        EndpointSpec(
                            id="get_users",
                            path="/api/users",
                            method="GET",
                            business_purpose="List all users",
                            requires_auth=True,
                            observed_count=5,
                            request=RequestSpec(content_type="application/json"),
                            responses=[
                                ResponseSpec(
                                    status=200, content_type="application/json"
                                ),
                            ],
                        )
                    ],
                ),
            ),
            business_glossary={"user": "A registered person"},
        )
        json_str = spec.model_dump_json(by_alias=True)
        loaded = ApiSpec.model_validate_json(json_str)
        assert loaded.name == "Test API"
        assert len(loaded.protocols.rest.endpoints) == 1
        assert loaded.protocols.rest.endpoints[0].id == "get_users"
        assert loaded.business_glossary["user"] == "A registered person"

    def test_response_schema_alias(self):
        """Test that 'schema' field uses alias correctly."""
        resp = ResponseSpec(
            status=200,
            schema={"type": "object", "properties": {"id": {"type": "integer"}}},
        )
        dumped = resp.model_dump(by_alias=True)
        assert "schema" in dumped
        assert dumped["schema"]["type"] == "object"

    def test_endpoint_with_ui_triggers(self):
        ep = EndpointSpec(
            id="test",
            path="/test",
            method="GET",
            ui_triggers=[
                UiTrigger(
                    action="click",
                    element_selector="button#test",
                    element_text="Test",
                    page_url="/page",
                    user_explanation="User clicked test button",
                )
            ],
        )
        assert len(ep.ui_triggers) == 1
        assert ep.ui_triggers[0].user_explanation == "User clicked test button"

    def test_parameter_spec(self):
        p = ParameterSpec(
            name="period",
            location="body",
            type="string",
            format="YYYY-MM",
            required=True,
            business_meaning="Billing period",
            example="2024-01",
            observed_values=["2024-01", "2024-02"],
        )
        assert p.format == "YYYY-MM"
        assert p.business_meaning == "Billing period"

    def test_ws_connection_spec(self):
        ws = WsConnectionSpec(
            id="ws_001",
            url="wss://example.com/ws",
            subprotocol="graphql-ws",
            messages=[
                WsMessageSpec(direction="send", label="subscribe"),
                WsMessageSpec(direction="receive", label="data"),
            ],
        )
        assert len(ws.messages) == 2
        assert ws.subprotocol == "graphql-ws"

    def test_api_spec_defaults(self):
        spec = ApiSpec()
        assert spec.api_spec_version == "1.0.0"
        assert spec.protocols.rest.endpoints == []
        assert spec.protocols.websocket.connections == []
        assert spec.business_glossary == {}

    def test_login_endpoint_config_roundtrip(self):
        config = LoginEndpointConfig(
            url="https://auth.example.com/oauth/token",
            method="POST",
            credential_fields={"username": "email", "password": "password"},
            extra_fields={"grant_type": "password", "client_id": "abc"},
            token_response_path="access_token",
            refresh_token_response_path="refresh_token",
        )
        json_str = config.model_dump_json()
        loaded = LoginEndpointConfig.model_validate_json(json_str)
        assert loaded.url == "https://auth.example.com/oauth/token"
        assert loaded.credential_fields == {"username": "email", "password": "password"}
        assert loaded.extra_fields["grant_type"] == "password"
        assert loaded.refresh_token_response_path == "refresh_token"

    def test_refresh_endpoint_config_roundtrip(self):
        config = RefreshEndpointConfig(
            url="https://auth.example.com/oauth/token",
            token_field="refresh_token",
            extra_fields={"grant_type": "refresh_token", "client_id": "abc"},
            token_response_path="access_token",
        )
        json_str = config.model_dump_json()
        loaded = RefreshEndpointConfig.model_validate_json(json_str)
        assert loaded.url == "https://auth.example.com/oauth/token"
        assert loaded.token_field == "refresh_token"
        assert loaded.extra_fields["grant_type"] == "refresh_token"

    def test_auth_info_with_login_and_refresh(self):
        auth = AuthInfo(
            type="bearer_token",
            token_header="Authorization",
            token_prefix="Bearer",
            login_config=LoginEndpointConfig(
                url="/auth/login",
                credential_fields={"email": "email", "password": "password"},
            ),
            refresh_config=RefreshEndpointConfig(
                url="/auth/refresh",
            ),
        )
        json_str = auth.model_dump_json()
        loaded = AuthInfo.model_validate_json(json_str)
        assert loaded.login_config is not None
        assert loaded.login_config.url == "/auth/login"
        assert loaded.refresh_config is not None
        assert loaded.refresh_config.url == "/auth/refresh"

    def test_auth_info_backward_compat(self):
        """Specs without login_config/refresh_config should still load."""
        data = {
            "type": "bearer_token",
            "obtain_flow": "login_form",
            "token_header": "Authorization",
            "token_prefix": "Bearer",
        }
        auth = AuthInfo.model_validate(data)
        assert auth.login_config is None
        assert auth.refresh_config is None
        assert auth.type == "bearer_token"

    def test_api_spec_with_auth_configs_roundtrip(self):
        spec = ApiSpec(
            name="Test",
            auth=AuthInfo(
                type="oauth2",
                login_config=LoginEndpointConfig(
                    url="https://auth0.example.com/oauth/token",
                    credential_fields={"username": "email", "password": "password"},
                    extra_fields={"grant_type": "password", "client_id": "xxx"},
                ),
                refresh_config=RefreshEndpointConfig(
                    url="https://auth0.example.com/oauth/token",
                    extra_fields={"grant_type": "refresh_token", "client_id": "xxx"},
                ),
            ),
        )
        json_str = spec.model_dump_json(by_alias=True)
        loaded = ApiSpec.model_validate_json(json_str)
        assert loaded.auth.login_config is not None
        assert loaded.auth.refresh_config is not None
        assert loaded.auth.login_config.extra_fields["client_id"] == "xxx"
