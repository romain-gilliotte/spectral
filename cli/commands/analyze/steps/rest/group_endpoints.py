"""Step: Group URLs into endpoint patterns using LLM."""

from __future__ import annotations

from typing import Any, cast

from cli.commands.analyze.steps.base import LLMStep, StepValidationError
from cli.commands.analyze.steps.rest.types import EndpointGroup
from cli.commands.analyze.steps.types import MethodUrlPair
from cli.commands.analyze.tools import (
    INVESTIGATION_TOOLS,
    TOOL_EXECUTORS,
)
from cli.commands.analyze.utils import compact_url
import cli.helpers.llm as llm


class GroupEndpointsStep(LLMStep[list[MethodUrlPair], list[EndpointGroup]]):
    """Ask the LLM to group URLs into endpoint patterns with {param} syntax.

    Input: list of MethodUrlPair (filtered to the base URL).
    Output: list of EndpointGroup with path patterns and assigned URLs.
    """

    name = "group_endpoints"

    async def _execute(self, input: list[MethodUrlPair]) -> list[EndpointGroup]:
        unique_pairs = sorted(set(input))
        compacted_pairs = sorted(
            set(MethodUrlPair(p.method, compact_url(p.url)) for p in unique_pairs)
        )
        lines = [f"  {p.method} {p.url}" for p in compacted_pairs]

        # Build mapping from compacted URL back to original URLs
        compact_to_originals: dict[MethodUrlPair, list[str]] = {}
        for p in unique_pairs:
            key = MethodUrlPair(p.method, compact_url(p.url))
            compact_to_originals.setdefault(key, []).append(p.url)

        prompt = f"""You are analyzing HTTP traffic captured from a web application.
Group these observed URLs into API endpoints. For each group, identify the path pattern
with parameters (use {{param_name}} syntax for variable segments).

Rules:
- Variable path segments (IDs, hashes, encoded values) become parameters like {{id}}, {{project_id}}, etc.
- Even if you only see ONE value for a segment, if it looks like an ID (numeric, UUID, hash, base64-like), parameterize it.
- Segments marked <base64:Nchars> are base64-encoded parameters — treat them as variable segments.
- Group URLs that represent the same logical endpoint together.
- Use the resource name before an ID to name the parameter (e.g., /projects/123 → /projects/{{project_id}}).
- Only include the path (no scheme, host, or query string) in the pattern.

You have investigation tools: decode_base64, decode_url, decode_jwt.
Use them when URL segments look opaque (base64-encoded, percent-encoded, or JWT tokens).
Decoding opaque segments will help you understand what they represent and group URLs correctly.

Observed requests:
{chr(10).join(lines)}

Respond with a JSON array:
[
  {{"method": "GET", "pattern": "/api/users/{{user_id}}/orders", "urls": ["https://example.com/api/users/123/orders", "https://example.com/api/users/456/orders"]}}
]"""

        text = await llm.ask(
            prompt,
            model=self.model,
            label="analyze_endpoints",
            tools=INVESTIGATION_TOOLS,
            executors=TOOL_EXECUTORS,
        )

        result = llm.extract_json(text)
        if not isinstance(result, list):
            raise ValueError("Expected a JSON array from analyze_endpoints")

        # Expand compacted URLs back to originals
        groups: list[EndpointGroup] = []
        for item in result:
            item_dict: dict[str, Any] = (
                cast(dict[str, Any], item) if isinstance(item, dict) else {}
            )
            compacted_urls: list[Any] = item_dict.get("urls", [])
            original_urls: list[str] = []
            for curl in compacted_urls:
                key = MethodUrlPair(item_dict["method"], curl)
                if key in compact_to_originals:
                    original_urls.extend(compact_to_originals[key])
                else:
                    original_urls.append(str(curl))
            groups.append(
                EndpointGroup(
                    method=str(item_dict["method"]),
                    pattern=str(item_dict["pattern"]),
                    urls=original_urls,
                )
            )
        return groups

    def _validate_output(self, output: list[EndpointGroup]) -> None:
        if not output:
            raise StepValidationError("No endpoint groups returned")
        seen: set[tuple[str, str]] = set()
        for group in output:
            key = (group.method, group.pattern)
            if key in seen:
                raise StepValidationError(
                    f"Duplicate endpoint group: {group.method} {group.pattern}",
                    {"method": group.method, "pattern": group.pattern},
                )
            seen.add(key)
