"""Group URLs into endpoint patterns using LLM."""

from __future__ import annotations

from cli.commands.openapi.analyze.types import EndpointGroup, EndpointGroupListResponse
from cli.helpers.detect_base_url import MethodUrlPair
from cli.helpers.http import compact_url
import cli.helpers.llm as llm


async def group_endpoints(pairs: list[MethodUrlPair]) -> list[EndpointGroup]:
    """Ask the LLM to group URLs into endpoint patterns with {param} syntax."""
    unique_pairs = sorted(set(pairs))
    compacted_pairs = sorted(
        set(MethodUrlPair(p.method, compact_url(p.url)) for p in unique_pairs)
    )
    lines = [f"  {p.method} {p.url}" for p in compacted_pairs]

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

Example format:
[{{"method": "GET", "pattern": "/api/users/{{user_id}}/orders", "urls": ["https://example.com/api/users/123/orders", "https://example.com/api/users/456/orders"]}}]"""

    conv = llm.Conversation(
        label="analyze_endpoints",
        tool_names=["decode_base64", "decode_url", "decode_jwt"],
    )
    response = await conv.ask_json(prompt, EndpointGroupListResponse)

    groups: list[EndpointGroup] = []
    for item in response.root:
        original_urls: list[str] = []
        for curl in item.urls:
            key = MethodUrlPair(item.method, curl)
            if key in compact_to_originals:
                original_urls.extend(compact_to_originals[key])
            else:
                original_urls.append(curl)
        groups.append(
            EndpointGroup(
                method=item.method,
                pattern=item.pattern,
                urls=original_urls,
            )
        )
    return groups
