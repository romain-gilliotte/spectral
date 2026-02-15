"""Step: Assemble the final ApiSpec from all pipeline components."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from cli.analyze.steps.base import MechanicalStep
from cli.formats.api_spec import (
    ApiSpec,
    AuthInfo,
    BusinessContext,
    EndpointSpec,
    Protocols,
    RestProtocol,
    WebSocketProtocol,
)


@dataclass
class AssembleInput:
    app_name: str
    source_filename: str
    base_url: str
    endpoints: list[EndpointSpec]
    auth: AuthInfo
    business_context: BusinessContext
    glossary: dict[str, str]
    ws_specs: WebSocketProtocol
    api_name: str | None = None


class AssembleStep(MechanicalStep[AssembleInput, ApiSpec]):
    """Combine all pipeline components into the final ApiSpec."""

    name = "assemble"

    async def _execute(self, input: AssembleInput) -> ApiSpec:
        return ApiSpec(
            name=input.api_name or input.app_name,
            discovery_date=datetime.now(timezone.utc).isoformat(),
            source_captures=[input.source_filename] if input.source_filename else [],
            business_context=input.business_context,
            auth=input.auth,
            protocols=Protocols(
                rest=RestProtocol(base_url=input.base_url, endpoints=input.endpoints),
                websocket=input.ws_specs,
            ),
            business_glossary=input.glossary,
        )
