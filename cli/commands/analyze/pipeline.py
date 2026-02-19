"""Orchestrator for the analysis pipeline.

Coordinates the Step instances to build an OpenAPI 3.1 spec from a capture
bundle. Auth analysis runs in parallel with endpoint enrichment.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cli.commands.analyze.correlator import correlate
from cli.commands.analyze.steps.analyze_auth import (
    AnalyzeAuthStep,
    detect_auth_mechanical,
)
from cli.commands.analyze.steps.assemble import AssembleStep
from cli.commands.analyze.steps.detect_base_url import DetectBaseUrlStep
from cli.commands.analyze.steps.enrich_and_context import EnrichEndpointsStep
from cli.commands.analyze.steps.extract_pairs import ExtractPairsStep
from cli.commands.analyze.steps.filter_traces import FilterTracesStep
from cli.commands.analyze.steps.group_endpoints import GroupEndpointsStep
from cli.commands.analyze.steps.mechanical_extraction import (
    MechanicalExtractionStep,
    extract_rate_limit,
    find_traces_for_group,
    has_auth_header_or_cookie,
)
from cli.commands.analyze.steps.strip_prefix import StripPrefixStep
from cli.commands.analyze.steps.types import (
    AuthInfo,
    EndpointSpec,
    EnrichmentContext,
    GroupedTraceData,
    GroupsWithBaseUrl,
    MethodUrlPair,
    SpecComponents,
    TracesWithBaseUrl,
)
from cli.commands.capture.types import CaptureBundle, Trace


async def build_spec(
    bundle: CaptureBundle,
    client: Any,
    model: str,
    source_filename: str = "",
    on_progress: Callable[[str], None] | None = None,
    enable_debug: bool = False,
    skip_enrich: bool = False,
) -> dict[str, Any]:
    """Build an OpenAPI 3.1 spec dict from a capture bundle.

    Pipeline:
    1. Extract (method, url) pairs from traces
    2. LLM detects business API base URL
    3. Filter traces by base URL
    4. LLM groups URLs into endpoint patterns
    5. Strip base_url path prefix from patterns
    6. Mechanical extraction (params, schemas)
    7. Detect auth & rate_limit per endpoint
    8. Per-endpoint LLM enrichment (parallel)  [parallel with auth]
    9. Auth analysis via LLM (on ALL unfiltered traces)  [parallel]
    10. Assemble final OpenAPI dict
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    # Debug directory
    debug_dir = None
    if enable_debug:
        run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        debug_dir = Path("debug") / run_ts
        debug_dir.mkdir(parents=True, exist_ok=True)
        progress(f"Debug logs → {debug_dir}")

    all_traces = list(bundle.traces)
    correlations = correlate(bundle)

    app_name = (
        bundle.manifest.app.name + " API"
        if bundle.manifest.app.name
        else "Discovered API"
    )

    # Step 1: Extract pairs
    extract_step = ExtractPairsStep()
    url_method_pairs = await extract_step.run(bundle)

    # Step 2: Detect base URL (LLM)
    progress("Detecting API base URL (LLM)...")
    detect_url_step = DetectBaseUrlStep(client, model, debug_dir)
    base_url = await detect_url_step.run(url_method_pairs)
    progress(f"  API base URL: {base_url}")

    # Step 3: Filter traces
    filter_step = FilterTracesStep()
    total_before = len(all_traces)
    filtered_traces = await filter_step.run(
        TracesWithBaseUrl(traces=all_traces, base_url=base_url)
    )
    progress(f"  Kept {len(filtered_traces)}/{total_before} traces under {base_url}")

    # Step 4: Group endpoints (LLM)
    progress("Grouping URLs into endpoints (LLM)...")
    filtered_pairs = [
        MethodUrlPair(t.meta.request.method.upper(), t.meta.request.url)
        for t in filtered_traces
    ]
    group_step = GroupEndpointsStep(client, model, debug_dir)
    endpoint_groups = await group_step.run(filtered_pairs)

    # Step 5: Strip prefix
    strip_step = StripPrefixStep()
    endpoint_groups = await strip_step.run(
        GroupsWithBaseUrl(groups=endpoint_groups, base_url=base_url)
    )

    # Debug mode: limit endpoints
    if debug_dir is not None and len(endpoint_groups) > 10:
        progress(f"Debug mode: limiting to 10/{len(endpoint_groups)} endpoints")
        endpoint_groups = endpoint_groups[:10]

    # Step 6: Mechanical extraction
    progress(f"Extracting {len(endpoint_groups)} endpoints...")
    mech_step = MechanicalExtractionStep()
    endpoints = await mech_step.run(
        GroupedTraceData(
            groups=endpoint_groups,
            traces=filtered_traces,
        )
    )

    # Step 7: Detect auth and rate_limit per endpoint
    _detect_auth_and_rate_limit(endpoints, endpoint_groups, filtered_traces)

    # Steps 8 & 9 run in parallel
    if skip_enrich:
        progress("Analyzing auth (enrichment skipped)...")
    else:
        progress("Enriching endpoints + analyzing auth...")

    async def _enrich() -> list[EndpointSpec] | None:
        if skip_enrich:
            return None
        enrich_step = EnrichEndpointsStep(client, model, debug_dir)
        try:
            return await enrich_step.run(
                EnrichmentContext(
                    endpoints=endpoints,
                    traces=filtered_traces,
                    correlations=correlations,
                    app_name=app_name,
                    base_url=base_url,
                )
            )
        except Exception:
            return None

    async def _auth() -> AuthInfo:
        auth_step = AnalyzeAuthStep(client, model, debug_dir)
        try:
            return await auth_step.run(all_traces)
        except Exception:
            return detect_auth_mechanical(all_traces)

    enrich_result, auth = await asyncio.gather(_enrich(), _auth())

    final_endpoints = enrich_result if enrich_result is not None else endpoints

    # Step 10: Assemble OpenAPI
    assemble_step = AssembleStep(traces=filtered_traces)
    openapi = await assemble_step.run(
        SpecComponents(
            app_name=app_name,
            source_filename=source_filename,
            base_url=base_url,
            endpoints=final_endpoints,
            auth=auth,
        )
    )

    return openapi


def _detect_auth_and_rate_limit(
    endpoints: list[EndpointSpec],
    endpoint_groups: list[Any],
    traces: list[Trace],
) -> None:
    """Detect requires_auth and rate_limit for each endpoint from traces."""
    for ep, group in zip(endpoints, endpoint_groups):
        group_traces = find_traces_for_group(group, traces)
        ep.requires_auth = any(has_auth_header_or_cookie(t) for t in group_traces)
        ep.rate_limit = extract_rate_limit(group_traces)
