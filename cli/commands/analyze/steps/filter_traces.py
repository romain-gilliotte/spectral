"""Step: Filter traces by base URL prefix."""

from __future__ import annotations

from cli.commands.analyze.steps.base import Step
from cli.commands.analyze.steps.types import TracesWithBaseUrl
from cli.commands.capture.types import Trace


class FilterTracesStep(Step[TracesWithBaseUrl, list[Trace]]):
    """Keep only traces whose URL starts with the detected base URL."""

    name = "filter_traces"

    async def _execute(self, input: TracesWithBaseUrl) -> list[Trace]:
        return [
            t for t in input.traces if t.meta.request.url.startswith(input.base_url)
        ]
