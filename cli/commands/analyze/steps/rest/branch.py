"""REST protocol branch: extraction, enrichment, and OpenAPI assembly."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cli.commands.analyze.schemas import resolve_map_candidates
from cli.commands.analyze.steps.analyze_auth import detect_auth_mechanical
from cli.commands.analyze.steps.base import ProtocolBranch
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
    EndpointGroup,
    EndpointSpec,
    EnrichmentContext,
    GroupedTraceData,
    GroupsWithBaseUrl,
    SpecComponents,
)
from cli.commands.analyze.steps.types import (
    BranchContext,
    BranchOutput,
    MethodUrlPair,
)
from cli.commands.capture.types import Trace


class RestBranch(ProtocolBranch):
    """REST analysis branch: groups → extract → enrich → assemble → OpenAPI."""

    protocol = "rest"
    file_extension = ".yaml"
    label = "OpenAPI 3.1 spec"

    async def run(
        self, traces: list[Trace], ctx: BranchContext
    ) -> BranchOutput | None:
        # Phase A: Mechanical extraction
        endpoints, _ = await _rest_extract(
            traces, ctx.base_url, ctx.on_progress
        )

        # Phase A.5: LLM map candidate resolution (before enrichment)
        if not ctx.skip_enrich:
            await _resolve_endpoint_maps(endpoints)

        # Phase B: Enrichment (optional)
        enriched: list[EndpointSpec] | None = None
        if not ctx.skip_enrich:
            enrich_step = EnrichEndpointsStep()
            try:
                enriched = await enrich_step.run(
                    EnrichmentContext(
                        endpoints=endpoints,
                        traces=ctx.all_filtered_traces,
                        correlations=ctx.correlations,
                        app_name=ctx.app_name,
                        base_url=ctx.base_url,
                    )
                )
            except Exception:
                enriched = None

        # Phase C: Await auth (needed for assembly)
        try:
            auth = await ctx.auth_task
        except Exception:
            auth = detect_auth_mechanical(ctx.all_filtered_traces)

        # Phase D: Assembly
        final_endpoints = enriched if enriched is not None else endpoints
        assemble_step = AssembleStep(traces=traces)
        openapi = await assemble_step.run(
            SpecComponents(
                app_name=ctx.app_name,
                source_filename=ctx.source_filename,
                base_url=ctx.base_url,
                endpoints=final_endpoints,
                auth=auth,
            )
        )

        return BranchOutput(
            protocol=self.protocol,
            artifact=openapi,
            file_extension=self.file_extension,
            label=self.label,
        )


async def _rest_extract(
    rest_traces: list[Trace],
    base_url: str,
    on_progress: Callable[[str], None],
) -> tuple[list[EndpointSpec], list[EndpointGroup]]:
    """Run REST extraction pipeline up to (but not including) enrichment."""
    # Group endpoints (LLM)
    on_progress("Grouping URLs into endpoints (LLM)...")
    filtered_pairs = [
        MethodUrlPair(t.meta.request.method.upper(), t.meta.request.url)
        for t in rest_traces
    ]
    group_step = GroupEndpointsStep()
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
    endpoint_groups: list[EndpointGroup],
    traces: list[Trace],
) -> None:
    """Detect requires_auth and rate_limit for each endpoint from traces."""
    for ep, group in zip(endpoints, endpoint_groups):
        group_traces = find_traces_for_group(group, traces)
        ep.requires_auth = any(has_auth_header_or_cookie(t) for t in group_traces)
        ep.rate_limit = extract_rate_limit(group_traces)


async def _resolve_endpoint_maps(endpoints: list[EndpointSpec]) -> None:
    """Collect all endpoint schemas and resolve map candidates via LLM."""
    all_schemas: list[dict[str, Any]] = []
    for ep in endpoints:
        if ep.request.body_schema:
            all_schemas.append(ep.request.body_schema)
        for resp in ep.responses:
            if resp.schema_:
                all_schemas.append(resp.schema_)
    await resolve_map_candidates(all_schemas)
