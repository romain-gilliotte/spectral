"""Load and write capture bundles (.zip files)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

from cli.commands.capture.types import CaptureBundle, Context, Trace, WsConnection, WsMessage
from cli.formats.capture_bundle import (
    CaptureManifest,
    ContextMeta,
    Timeline,
    TraceMeta,
    WsConnectionMeta,
    WsMessageMeta,
)


def load_bundle(path: str | Path) -> CaptureBundle:
    """Load a capture bundle from a .zip file on disk."""
    path = Path(path)
    with zipfile.ZipFile(path, "r") as zf:
        return _load_from_zipfile(zf)


def load_bundle_bytes(data: bytes) -> CaptureBundle:
    """Load a capture bundle from in-memory bytes."""
    with zipfile.ZipFile(BytesIO(data), "r") as zf:
        return _load_from_zipfile(zf)


def _load_from_zipfile(zf: zipfile.ZipFile) -> CaptureBundle:
    """Load a capture bundle from an open ZipFile."""
    manifest = CaptureManifest.model_validate_json(zf.read("manifest.json"))

    # Load traces
    traces: list[Trace] = []
    trace_files = sorted(
        n for n in zf.namelist() if n.startswith("traces/") and n.endswith(".json")
    )
    for tf in trace_files:
        trace_meta = TraceMeta.model_validate_json(zf.read(tf))
        req_body = b""
        resp_body = b""
        if trace_meta.request.body_file:
            req_path = f"traces/{trace_meta.request.body_file}"
            if req_path in zf.namelist():
                req_body = zf.read(req_path)
        if trace_meta.response.body_file:
            resp_path = f"traces/{trace_meta.response.body_file}"
            if resp_path in zf.namelist():
                resp_body = zf.read(resp_path)
        traces.append(
            Trace(meta=trace_meta, request_body=req_body, response_body=resp_body)
        )

    # Load WebSocket connections and messages
    ws_connections: list[WsConnection] = []
    ws_conn_files = sorted(
        n
        for n in zf.namelist()
        if n.startswith("ws/") and n.endswith(".json") and "_m" not in n.split("/")[-1]
    )
    for wf in ws_conn_files:
        ws_meta = WsConnectionMeta.model_validate_json(zf.read(wf))
        messages: list[WsMessage] = []
        # Find all message files for this connection
        ws_id = ws_meta.id
        msg_files = sorted(
            n
            for n in zf.namelist()
            if n.startswith(f"ws/{ws_id}_m") and n.endswith(".json")
        )
        for mf in msg_files:
            msg_meta = WsMessageMeta.model_validate_json(zf.read(mf))
            payload = b""
            if msg_meta.payload_file:
                payload_path = f"ws/{msg_meta.payload_file}"
                if payload_path in zf.namelist():
                    payload = zf.read(payload_path)
            messages.append(WsMessage(meta=msg_meta, payload=payload))
        ws_connections.append(WsConnection(meta=ws_meta, messages=messages))

    # Load contexts
    contexts: list[Context] = []
    ctx_files = sorted(
        n for n in zf.namelist() if n.startswith("contexts/") and n.endswith(".json")
    )
    for cf in ctx_files:
        ctx_meta = ContextMeta.model_validate_json(zf.read(cf))
        contexts.append(Context(meta=ctx_meta))

    # Load timeline
    timeline = Timeline()
    if "timeline.json" in zf.namelist():
        timeline = Timeline.model_validate_json(zf.read("timeline.json"))

    return CaptureBundle(
        manifest=manifest,
        traces=traces,
        ws_connections=ws_connections,
        contexts=contexts,
        timeline=timeline,
    )


def write_bundle(bundle: CaptureBundle, path: str | Path) -> None:
    """Write a capture bundle to a .zip file."""
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_to_zipfile(bundle, zf)


def write_bundle_bytes(bundle: CaptureBundle) -> bytes:
    """Write a capture bundle to in-memory bytes."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_to_zipfile(bundle, zf)
    return buf.getvalue()


def _write_to_zipfile(bundle: CaptureBundle, zf: zipfile.ZipFile) -> None:
    """Write all bundle data to an open ZipFile."""
    # Manifest
    zf.writestr("manifest.json", bundle.manifest.model_dump_json(indent=2))

    # Traces
    for trace in bundle.traces:
        meta = trace.meta
        zf.writestr(f"traces/{meta.id}.json", meta.model_dump_json(indent=2))
        if meta.request.body_file:
            zf.writestr(f"traces/{meta.request.body_file}", trace.request_body)
        if meta.response.body_file:
            zf.writestr(f"traces/{meta.response.body_file}", trace.response_body)

    # WebSocket connections and messages
    for ws_conn in bundle.ws_connections:
        ws_meta = ws_conn.meta
        zf.writestr(f"ws/{ws_meta.id}.json", ws_meta.model_dump_json(indent=2))
        for msg in ws_conn.messages:
            msg_meta = msg.meta
            zf.writestr(f"ws/{msg_meta.id}.json", msg_meta.model_dump_json(indent=2))
            if msg_meta.payload_file:
                zf.writestr(f"ws/{msg_meta.payload_file}", msg.payload)

    # Contexts
    for ctx in bundle.contexts:
        zf.writestr(f"contexts/{ctx.meta.id}.json", ctx.meta.model_dump_json(indent=2))

    # Timeline
    zf.writestr("timeline.json", bundle.timeline.model_dump_json(indent=2))
