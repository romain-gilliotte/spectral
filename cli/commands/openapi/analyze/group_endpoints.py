"""Group URLs into endpoint patterns using LLM."""

from __future__ import annotations

from cli.commands.openapi.analyze.types import EndpointGroup, EndpointGroupListResponse
from cli.helpers.detect_base_url import MethodUrlPair
from cli.helpers.http import compact_url
import cli.helpers.llm as llm
from cli.helpers.prompt import render


def group_endpoints(pairs: list[MethodUrlPair]) -> list[EndpointGroup]:
    """Ask the LLM to group URLs into endpoint patterns with {param} syntax."""
    unique_pairs = sorted(set(pairs))
    compacted_pairs = sorted(
        set(MethodUrlPair(p.method, compact_url(p.url)) for p in unique_pairs)
    )

    compact_to_originals: dict[MethodUrlPair, list[str]] = {}
    for p in unique_pairs:
        key = MethodUrlPair(p.method, compact_url(p.url))
        compact_to_originals.setdefault(key, []).append(p.url)

    prompt = render("openapi-group-endpoints.j2", pairs=compacted_pairs)

    conv = llm.Conversation(
        label="analyze_endpoints",
        tool_names=["decode_base64", "decode_url", "decode_jwt"],
    )
    response = conv.ask_json(prompt, EndpointGroupListResponse)

    groups: list[EndpointGroup] = []
    for item in response.items:
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
