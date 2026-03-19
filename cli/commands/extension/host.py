"""Chrome Native Messaging protocol: read/write length-prefixed JSON."""

from __future__ import annotations

import base64
import json
import struct
import sys
from typing import IO, Any

import click

from cli.commands.capture.types import (
    CaptureBundle,
    Context,
    Trace,
    WsConnection,
    WsMessage,
)
from cli.formats.capture_bundle import (
    CaptureManifest,
    ContextMeta,
    Timeline,
    TraceMeta,
    WsConnectionMeta,
    WsMessageMeta,
)
from cli.helpers.storage import DuplicateCaptureError, store_capture, validate_app_name


def read_message(stream: IO[bytes]) -> dict[str, Any]:
    """Read one length-prefixed JSON message from *stream*."""
    raw_length = stream.read(4)
    if len(raw_length) < 4:
        raise EOFError("No message (stream closed)")
    length = struct.unpack("<I", raw_length)[0]
    data = stream.read(length)
    if len(data) < length:
        raise EOFError("Truncated message")
    return json.loads(data)


def write_message(stream: IO[bytes], msg: dict[str, Any]) -> None:
    """Write one length-prefixed JSON message to *stream*."""
    data = json.dumps(msg).encode("utf-8")
    stream.write(struct.pack("<I", len(data)))
    stream.write(data)
    stream.flush()


def _decode_b64(value: str | None) -> bytes:
    if not value:
        return b""
    return base64.b64decode(value)


def deserialize_bundle(msg: dict[str, Any]) -> tuple[str, CaptureBundle]:
    """Convert a native messaging JSON payload into ``(app_name, CaptureBundle)``.

    Base64-encoded ``*_b64`` fields are decoded back to bytes.
    """
    app_name: str = msg["app_name"]
    validate_app_name(app_name)

    manifest = CaptureManifest.model_validate(msg["manifest"])

    # Traces
    traces: list[Trace] = []
    for t in msg.get("traces", []):
        request_body = _decode_b64(t.pop("request_body_b64", None))
        response_body = _decode_b64(t.pop("response_body_b64", None))
        meta = TraceMeta.model_validate(t)
        traces.append(Trace(meta=meta, request_body=request_body, response_body=response_body))

    # WebSocket connections
    ws_connections: list[WsConnection] = []
    for ws in msg.get("ws_connections", []):
        raw_messages = ws.pop("messages", [])
        ws_meta = WsConnectionMeta.model_validate(ws)
        messages: list[WsMessage] = []
        for m in raw_messages:
            payload = _decode_b64(m.pop("payload_b64", None))
            msg_meta = WsMessageMeta.model_validate(m)
            messages.append(WsMessage(meta=msg_meta, payload=payload))
        ws_connections.append(WsConnection(meta=ws_meta, messages=messages))

    # Contexts
    contexts: list[Context] = []
    for c in msg.get("contexts", []):
        contexts.append(Context(meta=ContextMeta.model_validate(c)))

    # Timeline
    timeline_data = msg.get("timeline", {})
    timeline = Timeline.model_validate(timeline_data) if timeline_data else Timeline()

    return app_name, CaptureBundle(
        manifest=manifest,
        traces=traces,
        ws_connections=ws_connections,
        contexts=contexts,
        timeline=timeline,
    )


def run_host() -> None:
    """Native messaging host entry point: read one message, process, respond."""
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    try:
        msg = read_message(stdin)
    except (EOFError, json.JSONDecodeError) as exc:
        write_message(stdout, {"type": "result", "success": False, "message": str(exc)})
        return

    msg_type = msg.get("type")

    if msg_type == "ping":
        write_message(stdout, {"type": "pong", "version": "0.1.0"})
        return

    if msg_type != "store_capture":
        write_message(stdout, {
            "type": "result",
            "success": False,
            "message": f"Unknown message type: {msg_type}",
        })
        return

    try:
        app_name, bundle = deserialize_bundle(msg)
        display_name = bundle.manifest.app.name
        store_capture(bundle, app_name, display_name=display_name)
        trace_count = len(bundle.traces)
        write_message(stdout, {
            "type": "result",
            "success": True,
            "app_name": app_name,
            "message": f"Imported {trace_count} traces",
        })
    except DuplicateCaptureError as exc:
        write_message(stdout, {
            "type": "result",
            "success": False,
            "message": f"Capture already imported ({exc.capture_id})",
        })
    except Exception as exc:
        write_message(stdout, {
            "type": "result",
            "success": False,
            "message": str(exc),
        })


@click.command()
def listen() -> None:
    """Native messaging host (called by Chrome, not by users directly)."""
    run_host()
