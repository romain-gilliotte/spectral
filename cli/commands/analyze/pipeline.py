"""Orchestrator for the analysis pipeline.

Coordinates the Step instances to build API specs from a capture bundle.
Supports both REST (-> OpenAPI 3.1) and GraphQL (-> SDL) traces.
Auth analysis runs in parallel with enrichment.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cli.commands.analyze.correlator import correlate
from cli.commands.analyze.protocol import detect_trace_protocol
from cli.commands.analyze.steps.analyze_auth import (
    AnalyzeAuthStep,
    detect_auth_mechanical,
)
from cli.commands.analyze.steps.detect_base_url import DetectBaseUrlStep
from cli.commands.analyze.steps.extract_pairs import ExtractPairsStep
from cli.commands.analyze.steps.filter_traces import FilterTracesStep
from cli.commands.analyze.steps.graphql.assemble import GraphQLAssembleStep
from cli.commands.analyze.steps.graphql.enrich import (
    GraphQLEnrichContext,
    GraphQLEnrichStep,
)
from cli.commands.analyze.steps.graphql.extraction import GraphQLExtractionStep
from cli.commands.analyze.steps.graphql.types import GraphQLSchemaData
from cli.commands.analyze.steps.rest.assemble import AssembleStep
from cli.commands.analyze.steps.rest.enrich import EnrichEndpointsStep
from cli.commands.analyze.steps.rest.extraction import (
    MechanicalExtractionStep,
    extract_rate_limit,
    find_traces_for_group,
    has_auth_header_or_cookie,
)
from cli.commands.analyze.steps.rest.group_endpoints import GroupEndpointsStep
from cli.commands.analyze.steps.rest.strip_prefix import StripPrefixStep
from cli.commands.analyze.steps.rest.types import (
    EndpointSpec,
    EnrichmentContext,
    GroupedTraceData,
    GroupsWithBaseUrl,
    SpecComponents,
)
from cli.commands.analyze.steps.types import (
    AuthInfo,
    MethodUrlPair,
    TracesWithBaseUrl,
)
from cli.commands.capture.types import CaptureBundle, Trace


@dataclass
class AnalysisResult:
    """Result of the analysis pipeline, supporting both REST and GraphQL."""

    openapi: dict[str, Any] | None = None
    graphql_sdl: str | None = None
    auth: AuthInfo | None = None
    base_url: str = ""
    auth_helper_script: str | None = None


async def build_spec(
    bundle: CaptureBundle,
    model: str,
    source_filename: str = "",
    on_progress: Callable[[str], None] | None = None,
    skip_enrich: bool = False,
) -> AnalysisResult:
    """Build API specs from a capture bundle.

    Returns an AnalysisResult with:
    - openapi: OpenAPI 3.1 dict (if REST traces found)
    - graphql_sdl: GraphQL SDL string (if GraphQL traces found)
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

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
    detect_url_step = DetectBaseUrlStep(model)
    base_url = await detect_url_step.run(url_method_pairs)
    progress(f"  API base URL: {base_url}")

    # Step 3: Filter traces
    filter_step = FilterTracesStep()
    total_before = len(all_traces)
    filtered_traces = await filter_step.run(
        TracesWithBaseUrl(traces=all_traces, base_url=base_url)
    )
    progress(f"  Kept {len(filtered_traces)}/{total_before} traces under {base_url}")

    # Step 4: Split by protocol
    rest_traces: list[Trace] = []
    graphql_traces: list[Trace] = []
    for t in filtered_traces:
        protocol = detect_trace_protocol(t)
        if protocol == "graphql":
            graphql_traces.append(t)
        else:
            rest_traces.append(t)

    has_rest = len(rest_traces) > 0
    has_graphql = len(graphql_traces) > 0

    if has_rest and has_graphql:
        progress(f"  REST traces: {len(rest_traces)}, GraphQL traces: {len(graphql_traces)}")
    elif has_graphql:
        progress(f"  GraphQL traces: {len(graphql_traces)} (no REST)")

    # Phase A: Mechanical extraction (can run in parallel for REST and GraphQL)
    rest_endpoints: list[EndpointSpec] | None = None
    graphql_schema: GraphQLSchemaData | None = None

    if has_rest:
        rest_endpoints, _ = await _rest_extract(
            rest_traces, base_url, model, progress
        )

    if has_graphql:
        progress("Extracting GraphQL schema from traces...")
        gql_step = GraphQLExtractionStep()
        graphql_schema = await gql_step.run(graphql_traces)
        type_count = len(graphql_schema.registry.types)
        enum_count = len(graphql_schema.registry.enums)
        progress(f"  Found {type_count} types, {enum_count} enums")

    # Phase B: Enrichment + Auth (parallel)
    async def _rest_enrich() -> list[EndpointSpec] | None:
        if not has_rest or rest_endpoints is None or skip_enrich:
            return None
        enrich_step = EnrichEndpointsStep(model)
        try:
            return await enrich_step.run(
                EnrichmentContext(
                    endpoints=rest_endpoints,
                    traces=filtered_traces,
                    correlations=correlations,
                    app_name=app_name,
                    base_url=base_url,
                )
            )
        except Exception:
            return None

    async def _graphql_enrich() -> GraphQLSchemaData | None:
        if not has_graphql or graphql_schema is None or skip_enrich:
            return None
        enrich_step = GraphQLEnrichStep(model)
        try:
            progress("Enriching GraphQL schema (LLM)...")
            return await enrich_step.run(
                GraphQLEnrichContext(
                    schema_data=graphql_schema,
                    traces=graphql_traces,
                    correlations=correlations,
                    app_name=app_name,
                )
            )
        except Exception:
            return None

    async def _auth() -> AuthInfo:
        auth_step = AnalyzeAuthStep(model)
        try:
            return await auth_step.run(all_traces)
        except Exception:
            return detect_auth_mechanical(all_traces)

    rest_enriched, gql_enriched, auth = await asyncio.gather(
        _rest_enrich(), _graphql_enrich(), _auth()
    )

    # Phase B2: Generate auth helper script (if interactive auth detected)
    auth_helper_script: str | None = None
    needs_script = (
        auth.type in ("bearer_token", "cookie")
        and auth.login_config is not None
        and not skip_enrich
    )
    if needs_script:
        from cli.commands.analyze.steps.generate_auth_script import (
            GenerateAuthScriptInput,
            GenerateAuthScriptStep,
        )

        progress("Generating auth helper script (LLM)...")
        try:
            script_step = GenerateAuthScriptStep(model)
            auth_helper_script = await script_step.run(
                GenerateAuthScriptInput(
                    auth=auth, traces=all_traces, api_name=app_name
                )
            )
        except Exception:
            progress("  Auth helper generation failed — skipping")

    # Phase C: Assembly
    openapi: dict[str, Any] | None = None
    graphql_sdl: str | None = None

    if has_rest and rest_endpoints is not None:
        final_endpoints = rest_enriched if rest_enriched is not None else rest_endpoints
        assemble_step = AssembleStep(traces=rest_traces)
        openapi = await assemble_step.run(
            SpecComponents(
                app_name=app_name,
                source_filename=source_filename,
                base_url=base_url,
                endpoints=final_endpoints,
                auth=auth,
            )
        )

    if has_graphql:
        final_schema = gql_enriched if gql_enriched is not None else graphql_schema
        if final_schema is not None:
            progress("Assembling GraphQL SDL...")
            gql_assemble = GraphQLAssembleStep()
            graphql_sdl = await gql_assemble.run(final_schema)

    return AnalysisResult(
        openapi=openapi,
        graphql_sdl=graphql_sdl,
        auth=auth,
        base_url=base_url,
        auth_helper_script=auth_helper_script,
    )


async def _rest_extract(
    rest_traces: list[Trace],
    base_url: str,
    model: str,
    on_progress: Callable[[str], None],
) -> tuple[list[EndpointSpec], list[Any]]:
    """Run REST extraction pipeline up to (but not including) enrichment."""
    # Group endpoints (LLM)
    on_progress("Grouping URLs into endpoints (LLM)...")
    filtered_pairs = [
        MethodUrlPair(t.meta.request.method.upper(), t.meta.request.url)
        for t in rest_traces
    ]
    group_step = GroupEndpointsStep(model)
    endpoint_groups = await group_step.run(filtered_pairs)

    # Strip prefix
    strip_step = StripPrefixStep()
    endpoint_groups = await strip_step.run(
        GroupsWithBaseUrl(groups=endpoint_groups, base_url=base_url)
    )

    # Mechanical extraction
    on_progress(f"Extracting {len(endpoint_groups)} endpoints...")
    mech_step = MechanicalExtractionStep()
    endpoints = await mech_step.run(
        GroupedTraceData(
            groups=endpoint_groups,
            traces=rest_traces,
        )
    )

    # Detect auth and rate_limit per endpoint
    _detect_auth_and_rate_limit(endpoints, endpoint_groups, rest_traces)

    return endpoints, endpoint_groups


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
