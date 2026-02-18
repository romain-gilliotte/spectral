"""Step: Filter traces by base URL prefix."""

from __future__ import annotations

from dataclasses import dataclass

from cli.analyze.steps.base import MechanicalStep
from cli.capture.models import Trace


@dataclass
class FilterInput:
    traces: list[Trace]
    base_url: str


class FilterTracesStep(MechanicalStep[FilterInput, list[Trace]]):
    """Keep only traces whose URL starts with the detected base URL."""

    name = "filter_traces"

    async def _execute(self, input: FilterInput) -> list[Trace]:
        return [
            t for t in input.traces if t.meta.request.url.startswith(input.base_url)
        ]
