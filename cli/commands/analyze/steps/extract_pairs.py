"""Step: Extract (method, url) pairs from traces."""

from __future__ import annotations

from cli.commands.analyze.steps.base import MechanicalStep
from cli.commands.analyze.steps.types import MethodUrlPair
from cli.commands.capture.types import CaptureBundle


class ExtractPairsStep(MechanicalStep[CaptureBundle, list[MethodUrlPair]]):
    """Extract (method, url) pairs from all traces in a capture bundle."""

    name = "extract_pairs"

    async def _execute(self, input: CaptureBundle) -> list[MethodUrlPair]:
        return [
            MethodUrlPair(t.meta.request.method.upper(), t.meta.request.url)
            for t in input.traces
        ]
