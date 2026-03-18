"""REST analysis pipeline: groups → extract → enrich → assemble → OpenAPI."""

from __future__ import annotations

from typing import Any

from cli.commands.capture.types import Trace
from cli.commands.openapi.analyze.assemble import assemble_openapi
from cli.commands.openapi.analyze.enrich import enrich_endpoints
from cli.commands.openapi.analyze.extraction import (
    extract_rate_limit,
    find_traces_for_group,
    mechanical_extraction,
)
from cli.commands.openapi.analyze.group_endpoints import group_endpoints
from cli.commands.openapi.analyze.strip_prefix import strip_prefix
from cli.commands.openapi.analyze.types import (
    EndpointGroup,
    EndpointSpec,
    EnrichmentContext,
    SpecComponents,
)
from cli.helpers.console import console
from cli.helpers.correlator import Correlation
from cli.helpers.detect_base_url import MethodUrlPair


def rest_analyze(
    traces: list[Trace],
    base_url: str,
    app_name: str,
    source_filename: str,
    correlations: list[Correlation],
    skip_enrich: bool,
) -> dict[str, Any]:
    """Run the full REST analysis pipeline and return an OpenAPI 3.1 dict."""
    # Phase A: Mechanical extraction (includes map resolution via analyze_schema)
    endpoints, _ = _rest_extract(traces, base_url)

    # Phase B: Enrichment (optional)
    enriched: list[EndpointSpec] | None = None
    if not skip_enrich:
        try:
            enriched = enrich_endpoints(
                EnrichmentContext(
                    endpoints=endpoints,
                    traces=traces,
                    correlations=correlations,
                    app_name=app_name,
                    base_url=base_url,
                )
            )
        except Exception:
            enriched = None

    # Phase C: Assembly
    final_endpoints = enriched if enriched is not None else endpoints
    openapi = assemble_openapi(
        SpecComponents(
            app_name=app_name,
            source_filename=source_filename,
            base_url=base_url,
            endpoints=final_endpoints,
        ),
        traces=traces,
    )

    return openapi


def _rest_extract(
    rest_traces: list[Trace],
    base_url: str,
) -> tuple[list[EndpointSpec], list[EndpointGroup]]:
    """Run REST extraction pipeline up to (but not including) enrichment."""
    console.print("  Grouping URLs into endpoints (LLM)...")
    filtered_pairs = [
        MethodUrlPair(t.meta.request.method.upper(), t.meta.request.url)
        for t in rest_traces
    ]
    endpoint_groups = group_endpoints(filtered_pairs)

    endpoint_groups = strip_prefix(endpoint_groups, base_url)

    console.print(f"  Extracting {len(endpoint_groups)} endpoints...")
    endpoints = mechanical_extraction(endpoint_groups, rest_traces)

    # Detect rate_limit per endpoint
    for ep, group in zip(endpoints, endpoint_groups):
        group_traces = find_traces_for_group(group, rest_traces)
        ep.rate_limit = extract_rate_limit(group_traces)

    return endpoints, endpoint_groups
