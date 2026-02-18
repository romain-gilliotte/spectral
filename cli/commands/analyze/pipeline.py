"""Orchestrator for the analysis pipeline.

Coordinates the Step instances to build an enriched API spec from a capture
bundle. Auth and WebSocket analysis run in parallel with the main branch.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cli.commands.analyze.correlator import correlate
from cli.commands.analyze.steps.analyze_auth import AnalyzeAuthStep, detect_auth_mechanical
from cli.commands.analyze.steps.assemble import AssembleStep
from cli.commands.analyze.steps.build_ws_specs import BuildWsSpecsStep
from cli.commands.analyze.steps.detect_base_url import DetectBaseUrlStep
from cli.commands.analyze.steps.enrich_and_context import EnrichAndContextStep
from cli.commands.analyze.steps.extract_pairs import ExtractPairsStep
from cli.commands.analyze.steps.filter_traces import FilterTracesStep
from cli.commands.analyze.steps.group_endpoints import GroupEndpointsStep
from cli.commands.analyze.steps.mechanical_extraction import MechanicalExtractionStep
from cli.commands.analyze.steps.strip_prefix import StripPrefixStep
from cli.commands.analyze.steps.types import (
    EnrichmentContext,
    GroupedTraceData,
    GroupsWithBaseUrl,
    MethodUrlPair,
    SpecComponents,
    TracesWithBaseUrl,
)
from cli.commands.capture.types import CaptureBundle
from cli.formats.api_spec import ApiSpec, BusinessContext


async def build_spec(
    bundle: CaptureBundle,
    client: Any,
    model: str,
    source_filename: str = "",
    on_progress: Callable[[str], None] | None = None,
    enable_debug: bool = False,
    skip_enrich: bool = False,
) -> ApiSpec:
    """Build an enriched API spec from a capture bundle.

    Pipeline:
    1. Extract (method, url) pairs from traces
    2. LLM detects business API base URL
    3. Filter traces by base URL
    4. LLM groups URLs into endpoint patterns
    5. Strip base_url path prefix from patterns
    6. Mechanical extraction (params, schemas, triggers)
    7. LLM enrichment + business context (single call)  [parallel with auth + ws]
    8. Auth analysis via LLM (on ALL unfiltered traces)  [parallel]
    9. WebSocket specs (mechanical)                       [parallel]
    10. Assemble final spec
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
            correlations=correlations,
        )
    )

    # Steps 7, 8, 9 run in parallel
    if skip_enrich:
        progress("Analyzing auth + building WS specs (enrichment skipped)...")
    else:
        progress("Enriching endpoints + analyzing auth + building WS specs...")

    async def _enrich() -> Any:
        if skip_enrich:
            return None
        enrich_step = EnrichAndContextStep(client, model, debug_dir)
        try:
            return await enrich_step.run(
                EnrichmentContext(
                    endpoints=endpoints,
                    traces=filtered_traces,
                    app_name=app_name,
                    base_url=base_url,
                    ws_connections=list(bundle.ws_connections) or None,
                )
            )
        except Exception:
            return None

    async def _auth() -> Any:
        auth_step = AnalyzeAuthStep(client, model, debug_dir)
        try:
            return await auth_step.run(all_traces)
        except Exception:
            return detect_auth_mechanical(all_traces)

    async def _ws() -> Any:
        ws_step = BuildWsSpecsStep()
        return await ws_step.run(bundle.ws_connections)

    enrich_result, auth, ws_specs = await asyncio.gather(_enrich(), _auth(), _ws())

    # Apply enrichment results (or use defaults)
    api_name: str | None = None
    ws_enrichments: dict[str, str] | None = None
    glossary: dict[str, str]
    if enrich_result is not None:
        final_endpoints = enrich_result.endpoints
        business_context = enrich_result.business_context
        glossary = enrich_result.glossary
        api_name = enrich_result.api_name
        ws_enrichments = enrich_result.ws_enrichments
    else:
        final_endpoints = endpoints
        business_context = BusinessContext(
            domain="",
            description=f"API discovered from {bundle.manifest.app.base_url}",
        )
        glossary = {}

    # Step 10: Assemble
    assemble_step = AssembleStep()
    spec = await assemble_step.run(
        SpecComponents(
            app_name=app_name,
            source_filename=source_filename,
            base_url=base_url,
            endpoints=final_endpoints,
            auth=auth,
            business_context=business_context,
            glossary=glossary,
            ws_specs=ws_specs,
            api_name=api_name,
        )
    )

    # Apply WS enrichments (business_purpose) to WebSocket connections
    if ws_enrichments:
        for ws_conn in spec.protocols.websocket.connections:
            if ws_conn.id in ws_enrichments:
                ws_conn.business_purpose = ws_enrichments[ws_conn.id]

    return spec
