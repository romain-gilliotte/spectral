"""Orchestrator for the analysis pipeline.

Coordinates protocol branches to build API specs from a capture bundle.
Each protocol (REST, GraphQL, ...) is encapsulated in a ProtocolBranch;
the pipeline dispatches traces and runs branches in parallel.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from cli.commands.analyze.correlator import correlate
from cli.commands.analyze.protocol import detect_trace_protocol
from cli.commands.analyze.steps.base import ProtocolBranch
from cli.commands.analyze.steps.detect_base_url import DetectBaseUrlStep
from cli.commands.analyze.steps.extract_pairs import ExtractPairsStep
from cli.commands.analyze.steps.filter_traces import FilterTracesStep
from cli.commands.analyze.steps.graphql.branch import GraphQLBranch
from cli.commands.analyze.steps.other.skip import UnsupportedBranch
from cli.commands.analyze.steps.rest.branch import RestBranch
from cli.commands.analyze.steps.types import (
    AnalysisResult,
    BranchContext,
    TracesWithBaseUrl,
)
from cli.commands.capture.types import CaptureBundle, Trace

# Branch registry — add new protocols here.
_BRANCHES: list[ProtocolBranch] = [RestBranch(), GraphQLBranch(), UnsupportedBranch()]


async def build_spec(
    bundle: CaptureBundle,
    source_filename: str = "",
    on_progress: Callable[[str], None] | None = None,
    skip_enrich: bool = False,
    protocol_filter: str | None = None,
) -> AnalysisResult:
    """Build API specs from a capture bundle.

    Returns an AnalysisResult with outputs for each detected protocol.
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
    detect_url_step = DetectBaseUrlStep(app_name=source_filename)
    base_url = await detect_url_step.run(url_method_pairs)
    progress(f"  API base URL: {base_url}")

    # Step 3: Filter traces
    filter_step = FilterTracesStep()
    total_before = len(all_traces)
    filtered_traces = await filter_step.run(
        TracesWithBaseUrl(traces=all_traces, base_url=base_url)
    )
    progress(f"  Kept {len(filtered_traces)}/{total_before} traces under {base_url}")

    # Step 4: Split by protocol using branch registry
    specific_branches = {b.protocol: b for b in _BRANCHES if not b.catch_all}
    catch_all_branch = next((b for b in _BRANCHES if b.catch_all), None)
    traces_by_protocol: dict[str, list[Trace]] = {}

    for t in filtered_traces:
        protocol = detect_trace_protocol(t)
        if protocol in specific_branches:
            traces_by_protocol.setdefault(protocol, []).append(t)
        elif catch_all_branch is not None:
            traces_by_protocol.setdefault(catch_all_branch.protocol, []).append(t)

    # Progress: report counts for each specific protocol that has traces
    active_specific = [
        f"{specific_branches[p].label}: {len(traces_by_protocol[p])}"
        for p in sorted(specific_branches)
        if p in traces_by_protocol
    ]
    if active_specific:
        progress(f"  {', '.join(active_specific)}")

    ctx = BranchContext(
        base_url=base_url,
        app_name=app_name,
        source_filename=source_filename,
        correlations=correlations,
        all_filtered_traces=filtered_traces,
        skip_enrich=skip_enrich,
        on_progress=progress,
    )

    # Launch all branches with traces in parallel
    branch_coros = [
        branch.run(traces_by_protocol[branch.protocol], ctx)
        for branch in _BRANCHES
        if branch.protocol in traces_by_protocol
        and (protocol_filter is None or branch.protocol == protocol_filter or branch.catch_all)
    ]
    branch_results = await asyncio.gather(*branch_coros)
    outputs = [r for r in branch_results if r is not None]

    return AnalysisResult(
        outputs=outputs,
        base_url=base_url,
    )
