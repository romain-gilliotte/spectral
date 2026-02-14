"""Pydantic models for the enriched API specification format (.json)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowStep(BaseModel):
    name: str
    description: str = ""
    steps: list[str] = Field(default_factory=list)


class BusinessContext(BaseModel):
    domain: str = ""
    description: str = ""
    user_personas: list[str] = Field(default_factory=list)
    key_workflows: list[WorkflowStep] = Field(default_factory=list)


class LoginEndpointConfig(BaseModel):
    url: str
    method: str = "POST"
    credential_fields: dict[str, str] = Field(default_factory=dict)
    extra_fields: dict[str, str] = Field(default_factory=dict)
    content_type: str = "application/json"
    token_response_path: str = "access_token"
    refresh_token_response_path: str = ""


class RefreshEndpointConfig(BaseModel):
    url: str
    method: str = "POST"
    token_field: str = "refresh_token"
    extra_fields: dict[str, str] = Field(default_factory=dict)
    token_response_path: str = "access_token"
    content_type: str = "application/json"


class AuthInfo(BaseModel):
    type: str = ""
    obtain_flow: str = ""
    business_process: str | None = None
    user_journey: list[str] = Field(default_factory=list)
    token_header: str | None = None
    token_prefix: str | None = None
    login_config: LoginEndpointConfig | None = None
    refresh_config: RefreshEndpointConfig | None = None
    discovery_notes: str | None = None


class UiTrigger(BaseModel):
    action: str = ""
    element_selector: str = ""
    element_text: str = ""
    page_url: str = ""
    user_explanation: str | None = None  # LLM-inferred


class ParameterSpec(BaseModel):
    name: str
    location: str = "body"  # "body" | "query" | "path" | "header"
    type: str = "string"
    format: str | None = None
    required: bool = False
    business_meaning: str | None = None  # LLM-inferred
    example: str | None = None
    constraints: str | None = None  # LLM-inferred
    observed_values: list[str] = Field(default_factory=list)


class RequestSpec(BaseModel):
    content_type: str | None = None
    parameters: list[ParameterSpec] = Field(default_factory=list)


class ResponseSpec(BaseModel):
    status: int
    content_type: str | None = None
    business_meaning: str | None = None  # LLM-inferred
    example_scenario: str | None = None  # LLM-inferred
    schema_: dict | None = Field(default=None, alias="schema")
    example_body: dict | str | list | None = None
    user_impact: str | None = None  # LLM-inferred
    resolution: str | None = None  # LLM-inferred

    model_config = {"populate_by_name": True}


class EndpointSpec(BaseModel):
    id: str
    path: str
    method: str
    business_purpose: str | None = None  # LLM-inferred
    user_story: str | None = None  # LLM-inferred
    ui_triggers: list[UiTrigger] = Field(default_factory=list)
    request: RequestSpec = Field(default_factory=RequestSpec)
    responses: list[ResponseSpec] = Field(default_factory=list)
    rate_limit: str | None = None
    requires_auth: bool = False
    correlation_confidence: float | None = None  # LLM-inferred
    discovery_notes: str | None = None
    observed_count: int = 0
    source_trace_refs: list[str] = Field(default_factory=list)


class RestProtocol(BaseModel):
    base_url: str = ""
    endpoints: list[EndpointSpec] = Field(default_factory=list)


class WsMessageSpec(BaseModel):
    direction: str = ""
    label: str = ""
    business_purpose: str | None = None  # LLM-inferred
    payload_schema: dict | None = None
    example_payload: dict | str | None = None


class WsConnectionSpec(BaseModel):
    id: str
    url: str
    subprotocol: str | None = None
    business_purpose: str | None = None  # LLM-inferred
    messages: list[WsMessageSpec] = Field(default_factory=list)


class WebSocketProtocol(BaseModel):
    connections: list[WsConnectionSpec] = Field(default_factory=list)


class Protocols(BaseModel):
    rest: RestProtocol = Field(default_factory=RestProtocol)
    websocket: WebSocketProtocol = Field(default_factory=WebSocketProtocol)


class ApiSpec(BaseModel):
    api_spec_version: str = "1.0.0"
    name: str = ""
    discovery_date: str = ""
    source_captures: list[str] = Field(default_factory=list)
    business_context: BusinessContext = Field(default_factory=BusinessContext)
    auth: AuthInfo = Field(default_factory=AuthInfo)
    protocols: Protocols = Field(default_factory=Protocols)
    business_glossary: dict[str, str] = Field(default_factory=dict)
