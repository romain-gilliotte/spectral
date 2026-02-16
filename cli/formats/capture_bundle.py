"""Pydantic models for the capture bundle format (.zip)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Header(BaseModel):
    name: str
    value: str


class AppInfo(BaseModel):
    name: str
    base_url: str
    title: str


class BrowserInfo(BaseModel):
    name: str
    version: str


class CaptureStats(BaseModel):
    trace_count: int = 0
    ws_connection_count: int = 0
    ws_message_count: int = 0
    context_count: int = 0


class CaptureManifest(BaseModel):
    format_version: str = "1.0.0"
    capture_id: str
    created_at: str
    app: AppInfo
    browser: BrowserInfo | None = None
    extension_version: str | None = "0.1.0"
    duration_ms: int
    stats: CaptureStats
    capture_method: str = "chrome_extension"


class RequestMeta(BaseModel):
    method: str
    url: str
    headers: list[Header] = Field(default_factory=list)
    body_file: str | None = None
    body_size: int = 0
    body_encoding: str | None = None


class ResponseMeta(BaseModel):
    status: int
    status_text: str = ""
    headers: list[Header] = Field(default_factory=list)
    body_file: str | None = None
    body_size: int = 0
    body_encoding: str | None = None


class TimingInfo(BaseModel):
    dns_ms: float = 0
    connect_ms: float = 0
    tls_ms: float = 0
    send_ms: float = 0
    wait_ms: float = 0
    receive_ms: float = 0
    total_ms: float = 0


class Initiator(BaseModel):
    type: str = "other"
    url: str | None = None
    line: int | None = None


class TraceMeta(BaseModel):
    id: str
    timestamp: int
    type: str = "http"
    request: RequestMeta
    response: ResponseMeta
    timing: TimingInfo = Field(default_factory=TimingInfo)
    initiator: Initiator = Field(default_factory=Initiator)
    context_refs: list[str] = Field(default_factory=list)


class WsConnectionMeta(BaseModel):
    id: str
    timestamp: int
    url: str
    handshake_trace_ref: str | None = None
    protocols: list[str] = Field(default_factory=list)
    message_count: int = 0
    context_refs: list[str] = Field(default_factory=list)


class WsMessageMeta(BaseModel):
    id: str
    connection_ref: str
    timestamp: int
    direction: str  # "send" | "receive"
    opcode: str = "text"  # "text" | "binary" | "ping" | "pong" | "close"
    payload_file: str | None = None
    payload_size: int = 0
    context_refs: list[str] = Field(default_factory=list)


class ElementInfo(BaseModel):
    selector: str = ""
    tag: str = ""
    text: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    xpath: str = ""


class PageContent(BaseModel):
    """Rich page context for LLM analysis."""

    headings: list[str] = Field(default_factory=list)
    navigation: list[str] = Field(default_factory=list)
    main_text: str = ""
    forms: list[dict] = Field(default_factory=list)  # [{id, fields, submitLabel}]
    tables: list[str] = Field(default_factory=list)  # Header rows
    alerts: list[str] = Field(default_factory=list)


class PageInfo(BaseModel):
    url: str
    title: str = ""
    content: PageContent | None = None  # Optional for backward compatibility


class ViewportInfo(BaseModel):
    width: int = 0
    height: int = 0
    scroll_x: int = 0
    scroll_y: int = 0


class ContextMeta(BaseModel):
    id: str
    timestamp: int
    action: str  # "click" | "input" | "submit" | "navigate" | "scroll"
    element: ElementInfo = Field(default_factory=ElementInfo)
    page: PageInfo
    viewport: ViewportInfo = Field(default_factory=ViewportInfo)


class TimelineEvent(BaseModel):
    timestamp: int
    type: str  # "context" | "trace" | "ws_open" | "ws_message"
    ref: str


class Timeline(BaseModel):
    events: list[TimelineEvent] = Field(default_factory=list)
