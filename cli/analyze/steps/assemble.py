"""Step: Assemble the final ApiSpec from all pipeline components."""

from __future__ import annotations

from datetime import datetime, timezone

from cli.analyze.steps.base import MechanicalStep
from cli.analyze.steps.types import SpecComponents
from cli.formats.api_spec import (
    ApiSpec,
    Protocols,
    RestProtocol,
)


class AssembleStep(MechanicalStep[SpecComponents, ApiSpec]):
    """Combine all pipeline components into the final ApiSpec."""

    name = "assemble"

    async def _execute(self, input: SpecComponents) -> ApiSpec:
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
