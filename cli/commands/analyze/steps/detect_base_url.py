"""Step: Detect the business API base URL using LLM."""

from __future__ import annotations

from collections import Counter
from typing import Any

from cli.commands.analyze.steps.base import LLMStep, StepValidationError
from cli.commands.analyze.steps.types import MethodUrlPair
from cli.commands.analyze.tools import (
    INVESTIGATION_TOOLS,
    TOOL_EXECUTORS,
)
from cli.commands.analyze.utils import compact_url
import cli.helpers.llm as llm


class DetectBaseUrlStep(LLMStep[list[MethodUrlPair], str]):
    """Ask the LLM to identify the business API base URL from captured traffic.

    Input: list of MethodUrlPair.
    Output: base URL string like "https://api.example.com" or "https://www.example.com/api".
    """

    name = "detect_base_url"

    async def _execute(self, input: list[MethodUrlPair]) -> str:
        counts = Counter(
            MethodUrlPair(p.method, compact_url(p.url)) for p in input
        )
        lines = [
            f"  {p.method} {p.url} ({n}x)" if n > 1 else f"  {p.method} {p.url}"
            for p, n in sorted(counts.items())
        ]

        prompt = f"""You are analyzing HTTP traffic captured from a web application.
Identify the base URL of the **business API** (the main application API, not CDN, analytics, tracking, fonts, or third-party services).

The base URL can be:
- Just the origin: https://api.example.com
- Origin + path prefix: https://www.example.com/api

Rules:
- Pick the single most important API base URL — the one serving the app's core business endpoints.
- Ignore CDN domains, analytics (google-analytics, hotjar, segment, etc.), ad trackers, font services, static asset hosts.
- If the API endpoints share a common path prefix (e.g. /api/v1), include it.
- A single URL called many times (e.g. POST /graphql) often indicates a GraphQL API — that's still a valid business API.
- Return ONLY the base URL string, no trailing slash.

Observed requests (call count shown when > 1):
{chr(10).join(lines)}

Respond with a JSON object:
{{"base_url": "https://..."}}"""

        text = await llm.call_with_tools(
            self.model,
            [{"role": "user", "content": prompt}],
            INVESTIGATION_TOOLS,
            TOOL_EXECUTORS,
            call_name="detect_api_base_url",
        )

        result = llm.extract_json(text)
        if isinstance(result, dict) and "base_url" in result:
            base_url: Any = result["base_url"]
            return str(base_url).rstrip("/")
        raise ValueError(
            f'Expected {{"base_url": "..."}} from detect_api_base_url, got: {text[:200]}'
        )

    def _validate_output(self, output: str) -> None:
        if not output.startswith("http"):
            raise StepValidationError(
                f"Invalid base URL: {output}",
                {"base_url": output},
            )
