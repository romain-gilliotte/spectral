"""HAR (HTTP Archive) import/export utilities.

HAR → Capture Bundle: import existing HAR recordings
Capture Bundle → HAR: export for compatibility (lossy: no UI context, binary→base64)
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cli.capture.models import CaptureBundle, Context, Trace, WsConnection
from cli.formats.capture_bundle import (
    AppInfo,
    BrowserInfo,
    CaptureManifest,
    CaptureStats,
    Header,
    Initiator,
    RequestMeta,
    ResponseMeta,
    Timeline,
    TimelineEvent,
    TimingInfo,
    TraceMeta,
)


def har_to_bundle(har_path: Path) -> CaptureBundle:
    """Convert a HAR file to a capture bundle."""
    with open(har_path) as f:
        har = json.load(f)

    log = har.get("log", har)
    entries = log.get("entries", [])

    # Extract metadata
    creator = log.get("creator", {})
    browser = log.get("browser", {})
    pages = log.get("pages", [])

    # Determine app info from first page or first entry
    base_url = ""
    app_name = ""
    app_title = ""
    if pages:
        app_title = pages[0].get("title", "")
    if entries:
        from urllib.parse import urlparse
        first_url = entries[0].get("request", {}).get("url", "")
        parsed = urlparse(first_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        app_name = parsed.netloc

    # Build traces
    traces: list[Trace] = []
    timeline_events: list[TimelineEvent] = []
    start_time = None

    for i, entry in enumerate(entries):
        trace_id = f"t_{i + 1:04d}"

        # Parse timestamp
        started = entry.get("startedDateTime", "")
        ts = _parse_iso_timestamp(started)
        if start_time is None:
            start_time = ts

        # Request
        req = entry.get("request", {})
        req_headers = [
            Header(name=h["name"], value=h["value"])
            for h in req.get("headers", [])
        ]
        req_body = b""
        post_data = req.get("postData", {})
        if post_data:
            text = post_data.get("text", "")
            if text:
                req_body = text.encode("utf-8")

        req_body_file = f"{trace_id}_request.bin" if req_body else None

        # Response
        resp = entry.get("response", {})
        resp_headers = [
            Header(name=h["name"], value=h["value"])
            for h in resp.get("headers", [])
        ]
        resp_body = b""
        content = resp.get("content", {})
        resp_text = content.get("text", "")
        if resp_text:
            encoding = content.get("encoding", "")
            if encoding == "base64":
                try:
                    resp_body = base64.b64decode(resp_text)
                except Exception:
                    resp_body = resp_text.encode("utf-8")
            else:
                resp_body = resp_text.encode("utf-8")

        resp_body_file = f"{trace_id}_response.bin" if resp_body else None

        # Timing
        timings = entry.get("timings", {})
        timing = TimingInfo(
            dns_ms=max(0, timings.get("dns", 0)),
            connect_ms=max(0, timings.get("connect", 0)),
            tls_ms=max(0, timings.get("ssl", 0)),
            send_ms=max(0, timings.get("send", 0)),
            wait_ms=max(0, timings.get("wait", 0)),
            receive_ms=max(0, timings.get("receive", 0)),
            total_ms=entry.get("time", 0),
        )

        trace_meta = TraceMeta(
            id=trace_id,
            timestamp=ts,
            type="http",
            request=RequestMeta(
                method=req.get("method", "GET"),
                url=req.get("url", ""),
                headers=req_headers,
                body_file=req_body_file,
                body_size=len(req_body),
            ),
            response=ResponseMeta(
                status=resp.get("status", 0),
                status_text=resp.get("statusText", ""),
                headers=resp_headers,
                body_file=resp_body_file,
                body_size=len(resp_body),
            ),
            timing=timing,
        )

        traces.append(Trace(meta=trace_meta, request_body=req_body, response_body=resp_body))
        timeline_events.append(TimelineEvent(timestamp=ts, type="trace", ref=trace_id))

    # Compute duration
    duration_ms = 0
    if traces:
        first_ts = traces[0].meta.timestamp
        last_ts = traces[-1].meta.timestamp
        last_timing = traces[-1].meta.timing.total_ms
        duration_ms = int(last_ts - first_ts + last_timing)

    manifest = CaptureManifest(
        capture_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        app=AppInfo(name=app_name, base_url=base_url, title=app_title),
        browser=BrowserInfo(
            name=browser.get("name", creator.get("name", "Unknown")),
            version=browser.get("version", creator.get("version", "0.0")),
        ),
        duration_ms=duration_ms,
        stats=CaptureStats(
            trace_count=len(traces),
        ),
    )

    return CaptureBundle(
        manifest=manifest,
        traces=traces,
        timeline=Timeline(events=timeline_events),
    )


def bundle_to_har(bundle: CaptureBundle) -> dict:
    """Convert a capture bundle to HAR format.

    This is lossy:
    - UI contexts are not included (HAR has no concept of this)
    - Binary bodies are base64-encoded
    - WebSocket messages use non-standard _webSocketMessages
    """
    entries = []

    for trace in bundle.traces:
        m = trace.meta

        # Request
        req_headers = [{"name": h.name, "value": h.value} for h in m.request.headers]
        request: dict = {
            "method": m.request.method,
            "url": m.request.url,
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": req_headers,
            "queryString": _extract_query_string(m.request.url),
            "headersSize": -1,
            "bodySize": m.request.body_size,
        }

        if trace.request_body:
            ct = _get_header(m.request.headers, "content-type") or ""
            request["postData"] = {
                "mimeType": ct,
                "text": _encode_body(trace.request_body),
            }

        # Response
        resp_headers = [{"name": h.name, "value": h.value} for h in m.response.headers]
        resp_ct = _get_header(m.response.headers, "content-type") or ""
        resp_body_text, resp_encoding = _encode_body_with_encoding(trace.response_body)

        response: dict = {
            "status": m.response.status,
            "statusText": m.response.status_text,
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": resp_headers,
            "content": {
                "size": m.response.body_size,
                "mimeType": resp_ct,
                "text": resp_body_text,
            },
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": m.response.body_size,
        }
        if resp_encoding:
            response["content"]["encoding"] = resp_encoding

        # Timings
        timings = {
            "dns": m.timing.dns_ms,
            "connect": m.timing.connect_ms,
            "ssl": m.timing.tls_ms,
            "send": m.timing.send_ms,
            "wait": m.timing.wait_ms,
            "receive": m.timing.receive_ms,
        }

        # Timestamp
        started = _timestamp_to_iso(m.timestamp)

        entry = {
            "startedDateTime": started,
            "time": m.timing.total_ms,
            "request": request,
            "response": response,
            "cache": {},
            "timings": timings,
        }
        entries.append(entry)

    har = {
        "log": {
            "version": "1.2",
            "creator": {
                "name": "api-discover",
                "version": "0.1.0",
            },
            "browser": {
                "name": bundle.manifest.browser.name,
                "version": bundle.manifest.browser.version,
            },
            "entries": entries,
        }
    }

    return har


def _parse_iso_timestamp(s: str) -> int:
    """Parse an ISO timestamp to Unix millis."""
    if not s:
        return 0
    try:
        # Handle various ISO formats
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return int(dt.timestamp() * 1000)
    except (ValueError, OSError):
        return 0


def _timestamp_to_iso(ts_ms: int) -> str:
    """Convert Unix millis to ISO timestamp string."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.isoformat()


def _extract_query_string(url: str) -> list[dict]:
    """Extract query string parameters from URL."""
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    result = []
    for name, values in qs.items():
        for value in values:
            result.append({"name": name, "value": value})
    return result


def _encode_body(body: bytes) -> str:
    """Encode body as text (UTF-8 if possible, else base64)."""
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return base64.b64encode(body).decode("ascii")


def _encode_body_with_encoding(body: bytes) -> tuple[str, str]:
    """Encode body with encoding indicator."""
    if not body:
        return "", ""
    try:
        return body.decode("utf-8"), ""
    except UnicodeDecodeError:
        return base64.b64encode(body).decode("ascii"), "base64"


def _get_header(headers: list, name: str) -> str | None:
    """Get a header value by name (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.name.lower() == name_lower:
            return h.value
    return None
