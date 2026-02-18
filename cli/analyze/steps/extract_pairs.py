"""Step: Extract (method, url) pairs from traces."""

from __future__ import annotations

from cli.analyze.steps.base import MechanicalStep
from cli.capture.models import CaptureBundle


class ExtractPairsStep(MechanicalStep[CaptureBundle, list[tuple[str, str]]]):
    """Extract (method, url) pairs from all traces in a capture bundle."""

    name = "extract_pairs"

    async def _execute(self, input: CaptureBundle) -> list[tuple[str, str]]:
        return [
            (t.meta.request.method.upper(), t.meta.request.url) for t in input.traces
        ]
