"""Step: Build WebSocket protocol specs from captured connections."""

from __future__ import annotations

import json
from typing import Any

from cli.analyze.protocol import detect_ws_protocol
from cli.analyze.schemas import infer_schema
from cli.analyze.steps.base import MechanicalStep
from cli.capture.models import WsConnection
from cli.formats.api_spec import (
    WebSocketProtocol,
    WsConnectionSpec,
    WsMessageSpec,
)


class BuildWsSpecsStep(MechanicalStep[list[WsConnection], WebSocketProtocol]):
    """Build WebSocket protocol specs from captured connections."""

    name = "build_ws_specs"

    async def _execute(self, input: list[WsConnection]) -> WebSocketProtocol:
        specs: list[WsConnectionSpec] = []
        for ws_conn in input:
            proto = detect_ws_protocol(ws_conn)

            messages: list[WsMessageSpec] = []
            for msg in ws_conn.messages:
                payload_example: Any = None
                payload_schema: dict[str, Any] | None = None
                if msg.payload:
                    try:
                        data = json.loads(msg.payload)
                        payload_example = data
                        if isinstance(data, dict):
                            payload_schema = infer_schema([data])
                            for prop in payload_schema.get("properties", {}).values():
                                prop.pop("observed", None)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass

                messages.append(
                    WsMessageSpec(
                        direction=msg.meta.direction,
                        label=f"{msg.meta.direction}_{msg.meta.id}",
                        payload_schema=payload_schema,
                        example_payload=payload_example,
                    )
                )

            specs.append(
                WsConnectionSpec(
                    id=ws_conn.meta.id,
                    url=ws_conn.meta.url,
                    subprotocol=proto if proto != "unknown" else None,
                    messages=messages,
                )
            )

        return WebSocketProtocol(connections=specs)
