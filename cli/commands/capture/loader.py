"""Load and write capture bundles (.zip files and flat directories)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

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


def load_bundle(path: str | Path) -> CaptureBundle:
    """Load a capture bundle from a .zip file on disk."""
    path = Path(path)
    with zipfile.ZipFile(path, "r") as zf:
        return _load_from_zipfile(zf)


def load_bundle_bytes(data: bytes) -> CaptureBundle:
    """Load a capture bundle from in-memory bytes."""
    with zipfile.ZipFile(BytesIO(data), "r") as zf:
        return _load_from_zipfile(zf)


def _read_zip_entry(zf: zipfile.ZipFile, path: str) -> bytes:
    """Read a binary entry from *zf*, returning ``b""`` if it does not exist."""
    if path in zf.namelist():
        return zf.read(path)
    return b""


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
        req_body = (
            _read_zip_entry(zf, f"traces/{trace_meta.request.body_file}")
            if trace_meta.request.body_file
            else b""
        )
        resp_body = (
            _read_zip_entry(zf, f"traces/{trace_meta.response.body_file}")
            if trace_meta.response.body_file
            else b""
        )
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
            payload = (
                _read_zip_entry(zf, f"ws/{msg_meta.payload_file}")
                if msg_meta.payload_file
                else b""
            )
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


# ---------------------------------------------------------------------------
# Flat-directory format (same layout as inside the ZIP, but on disk)
# ---------------------------------------------------------------------------


def write_bundle_dir(bundle: CaptureBundle, directory: str | Path) -> None:
    """Write a capture bundle as flat files in *directory*."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)

    (d / "manifest.json").write_text(bundle.manifest.model_dump_json(indent=2))

    # Traces
    traces_dir = d / "traces"
    if bundle.traces:
        traces_dir.mkdir(exist_ok=True)
    for trace in bundle.traces:
        meta = trace.meta
        (traces_dir / f"{meta.id}.json").write_text(meta.model_dump_json(indent=2))
        if meta.request.body_file:
            (traces_dir / meta.request.body_file).write_bytes(trace.request_body)
        if meta.response.body_file:
            (traces_dir / meta.response.body_file).write_bytes(trace.response_body)

    # WebSocket
    ws_dir = d / "ws"
    if bundle.ws_connections:
        ws_dir.mkdir(exist_ok=True)
    for ws_conn in bundle.ws_connections:
        ws_meta = ws_conn.meta
        (ws_dir / f"{ws_meta.id}.json").write_text(ws_meta.model_dump_json(indent=2))
        for msg in ws_conn.messages:
            msg_meta = msg.meta
            (ws_dir / f"{msg_meta.id}.json").write_text(msg_meta.model_dump_json(indent=2))
            if msg_meta.payload_file:
                (ws_dir / msg_meta.payload_file).write_bytes(msg.payload)

    # Contexts
    ctx_dir = d / "contexts"
    if bundle.contexts:
        ctx_dir.mkdir(exist_ok=True)
    for ctx in bundle.contexts:
        (ctx_dir / f"{ctx.meta.id}.json").write_text(ctx.meta.model_dump_json(indent=2))

    # Timeline
    (d / "timeline.json").write_text(bundle.timeline.model_dump_json(indent=2))


def load_bundle_dir(directory: str | Path) -> CaptureBundle:
    """Load a capture bundle from a flat-file directory."""
    d = Path(directory)
    manifest = CaptureManifest.model_validate_json((d / "manifest.json").read_text())

    # Traces
    traces: list[Trace] = []
    traces_dir = d / "traces"
    if traces_dir.is_dir():
        trace_files = sorted(traces_dir.glob("*.json"))
        for tf in trace_files:
            trace_meta = TraceMeta.model_validate_json(tf.read_text())
            req_body = (
                (traces_dir / trace_meta.request.body_file).read_bytes()
                if trace_meta.request.body_file
                and (traces_dir / trace_meta.request.body_file).exists()
                else b""
            )
            resp_body = (
                (traces_dir / trace_meta.response.body_file).read_bytes()
                if trace_meta.response.body_file
                and (traces_dir / trace_meta.response.body_file).exists()
                else b""
            )
            traces.append(
                Trace(meta=trace_meta, request_body=req_body, response_body=resp_body)
            )

    # WebSocket
    ws_connections: list[WsConnection] = []
    ws_dir = d / "ws"
    if ws_dir.is_dir():
        ws_conn_files = sorted(
            f for f in ws_dir.glob("*.json") if "_m" not in f.name
        )
        for wf in ws_conn_files:
            ws_meta = WsConnectionMeta.model_validate_json(wf.read_text())
            messages: list[WsMessage] = []
            ws_id = ws_meta.id
            msg_files = sorted(ws_dir.glob(f"{ws_id}_m*.json"))
            for mf in msg_files:
                msg_meta = WsMessageMeta.model_validate_json(mf.read_text())
                payload = (
                    (ws_dir / msg_meta.payload_file).read_bytes()
                    if msg_meta.payload_file
                    and (ws_dir / msg_meta.payload_file).exists()
                    else b""
                )
                messages.append(WsMessage(meta=msg_meta, payload=payload))
            ws_connections.append(WsConnection(meta=ws_meta, messages=messages))

    # Contexts
    contexts: list[Context] = []
    ctx_dir = d / "contexts"
    if ctx_dir.is_dir():
        for cf in sorted(ctx_dir.glob("*.json")):
            ctx_meta = ContextMeta.model_validate_json(cf.read_text())
            contexts.append(Context(meta=ctx_meta))

    # Timeline
    timeline = Timeline()
    timeline_path = d / "timeline.json"
    if timeline_path.exists():
        timeline = Timeline.model_validate_json(timeline_path.read_text())

    return CaptureBundle(
        manifest=manifest,
        traces=traces,
        ws_connections=ws_connections,
        contexts=contexts,
        timeline=timeline,
    )
