"""Tests for the Chrome Native Messaging host protocol and deserialization."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import struct
from typing import Any

import pytest

from cli.commands.extension.host import (
    deserialize_bundle,
    read_message,
    run_host,
    write_message,
)
from cli.helpers.storage import DuplicateCaptureError, store_capture

# ---------------------------------------------------------------------------
# Wire protocol
# ---------------------------------------------------------------------------


class TestReadWriteMessage:
    def test_roundtrip(self) -> None:
        msg = {"type": "store_capture", "app_name": "test"}
        buf = io.BytesIO()
        write_message(buf, msg)
        buf.seek(0)
        result = read_message(buf)
        assert result == msg

    def test_read_empty_stream(self) -> None:
        buf = io.BytesIO(b"")
        with pytest.raises(EOFError):
            read_message(buf)

    def test_read_truncated_body(self) -> None:
        # Write a length header claiming 100 bytes, but only provide 5.
        buf = io.BytesIO(struct.pack("<I", 100) + b"hello")
        with pytest.raises(EOFError, match="Truncated"):
            read_message(buf)

    def test_binary_safe(self) -> None:
        msg = {"data": "hello world", "number": 42}
        buf = io.BytesIO()
        write_message(buf, msg)
        raw = buf.getvalue()
        # Verify 4-byte LE prefix
        length = struct.unpack("<I", raw[:4])[0]
        assert length == len(raw) - 4
        assert json.loads(raw[4:]) == msg


# ---------------------------------------------------------------------------
# run_host ping
# ---------------------------------------------------------------------------


class TestRunHostPing:
    def test_ping_returns_pong(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Build a ping message
        stdin_buf = io.BytesIO()
        write_message(stdin_buf, {"type": "ping"})
        stdin_buf.seek(0)

        stdout_buf = io.BytesIO()
        monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"buffer": stdin_buf})())
        monkeypatch.setattr("sys.stdout", type("FakeStdout", (), {"buffer": stdout_buf})())

        run_host()

        stdout_buf.seek(0)
        response = read_message(stdout_buf)
        assert response["type"] == "pong"
        assert "version" in response


# ---------------------------------------------------------------------------
# Bundle deserialization
# ---------------------------------------------------------------------------


def _make_payload(
    *,
    app_name: str = "test-app",
    trace_count: int = 1,
    with_ws: bool = False,
    with_context: bool = False,
) -> dict[str, Any]:
    """Build a minimal native messaging payload."""
    manifest = {
        "format_version": "1.0.0",
        "capture_id": "cap-001",
        "created_at": "2026-01-01T00:00:00Z",
        "app": {"name": "Test", "base_url": "https://example.com", "title": "Test"},
        "browser": {"name": "Chrome", "version": "133.0"},
        "duration_ms": 5000,
        "stats": {
            "trace_count": trace_count,
            "ws_connection_count": 1 if with_ws else 0,
            "ws_message_count": 1 if with_ws else 0,
            "context_count": 1 if with_context else 0,
        },
    }

    traces: list[dict[str, Any]] = []
    for i in range(trace_count):
        tid = f"t_{i + 1:04d}"
        req_body = json.dumps({"key": "value"}).encode()
        resp_body = json.dumps({"result": "ok"}).encode()
        traces.append({
            "id": tid,
            "timestamp": 1000 + i,
            "type": "http",
            "request": {
                "method": "POST",
                "url": "https://example.com/api",
                "headers": [{"name": "Content-Type", "value": "application/json"}],
                "body_file": f"{tid}_request.bin",
                "body_size": len(req_body),
            },
            "response": {
                "status": 200,
                "status_text": "OK",
                "headers": [{"name": "Content-Type", "value": "application/json"}],
                "body_file": f"{tid}_response.bin",
                "body_size": len(resp_body),
            },
            "context_refs": [],
            "request_body_b64": base64.b64encode(req_body).decode(),
            "response_body_b64": base64.b64encode(resp_body).decode(),
        })

    ws_connections: list[dict[str, Any]] = []
    if with_ws:
        payload_bytes = b'{"type":"subscribe"}'
        ws_connections.append({
            "id": "ws_0001",
            "timestamp": 2000,
            "url": "wss://example.com/ws",
            "protocols": [],
            "message_count": 1,
            "context_refs": [],
            "messages": [{
                "id": "ws_0001_m001",
                "connection_ref": "ws_0001",
                "timestamp": 2001,
                "direction": "send",
                "opcode": "text",
                "payload_file": "ws_0001_m001.bin",
                "payload_size": len(payload_bytes),
                "context_refs": [],
                "payload_b64": base64.b64encode(payload_bytes).decode(),
            }],
        })

    contexts: list[dict[str, Any]] = []
    if with_context:
        contexts.append({
            "id": "c_0001",
            "timestamp": 900,
            "action": "click",
            "element": {"selector": "button#go", "tag": "BUTTON", "text": "Go"},
            "page": {"url": "https://example.com", "title": "Home"},
        })

    return {
        "type": "store_capture",
        "app_name": app_name,
        "manifest": manifest,
        "traces": traces,
        "ws_connections": ws_connections,
        "contexts": contexts,
        "timeline": {"events": []},
    }


class TestDeserializeBundle:
    def test_basic_traces(self) -> None:
        payload = _make_payload(trace_count=2)
        app_name, bundle = deserialize_bundle(payload)

        assert app_name == "test-app"
        assert bundle.manifest.capture_id == "cap-001"
        assert len(bundle.traces) == 2
        assert bundle.traces[0].meta.id == "t_0001"
        assert bundle.traces[0].request_body == json.dumps({"key": "value"}).encode()
        assert bundle.traces[0].response_body == json.dumps({"result": "ok"}).encode()

    def test_ws_connections(self) -> None:
        payload = _make_payload(with_ws=True)
        _, bundle = deserialize_bundle(payload)

        assert len(bundle.ws_connections) == 1
        ws = bundle.ws_connections[0]
        assert ws.meta.id == "ws_0001"
        assert len(ws.messages) == 1
        assert ws.messages[0].payload == b'{"type":"subscribe"}'

    def test_contexts(self) -> None:
        payload = _make_payload(with_context=True)
        _, bundle = deserialize_bundle(payload)

        assert len(bundle.contexts) == 1
        assert bundle.contexts[0].meta.id == "c_0001"
        assert bundle.contexts[0].meta.action == "click"

    def test_empty_bodies(self) -> None:
        payload = _make_payload(trace_count=1)
        # Remove base64 fields to simulate traces without bodies
        trace: dict[str, Any] = payload["traces"][0]  # type: ignore[assignment]
        trace.pop("request_body_b64")
        trace.pop("response_body_b64")
        _, bundle = deserialize_bundle(payload)

        assert bundle.traces[0].request_body == b""
        assert bundle.traces[0].response_body == b""


# ---------------------------------------------------------------------------
# Integration: deserialize + store
# ---------------------------------------------------------------------------


class TestStoreIntegration:
    def test_store_deserialized_bundle(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        payload = _make_payload(trace_count=3, with_ws=True, with_context=True)
        app_name, bundle = deserialize_bundle(payload)
        cap_dir = store_capture(bundle, app_name)

        assert cap_dir.is_dir()
        assert (cap_dir / "manifest.json").is_file()
        assert (cap_dir / "traces" / "t_0001.json").is_file()

    def test_duplicate_rejected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECTRAL_HOME", str(tmp_path))
        payload = _make_payload()
        app_name, bundle = deserialize_bundle(payload)
        store_capture(bundle, app_name)

        # Re-deserialize (can't reuse — dicts were mutated by pop)
        payload2 = _make_payload()
        _, bundle2 = deserialize_bundle(payload2)
        with pytest.raises(DuplicateCaptureError):
            store_capture(bundle2, app_name)
