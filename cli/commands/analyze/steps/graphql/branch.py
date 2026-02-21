"""GraphQL protocol branch: extraction, enrichment, and SDL assembly."""

from __future__ import annotations

from cli.commands.analyze.steps.base import ProtocolBranch
from cli.commands.analyze.steps.graphql.assemble import GraphQLAssembleStep
from cli.commands.analyze.steps.graphql.enrich import (
    GraphQLEnrichContext,
    GraphQLEnrichStep,
)
from cli.commands.analyze.steps.graphql.extraction import GraphQLExtractionStep
from cli.commands.analyze.steps.types import BranchContext, BranchOutput
from cli.commands.capture.types import Trace


class GraphQLBranch(ProtocolBranch):
    """GraphQL analysis branch: extract types → enrich → assemble SDL."""

    protocol = "graphql"
    file_extension = ".graphql"
    label = "GraphQL SDL schema"

    async def run(
        self, traces: list[Trace], ctx: BranchContext
    ) -> BranchOutput | None:
        # Phase A: Extraction
        ctx.on_progress("Extracting GraphQL schema from traces...")
        gql_step = GraphQLExtractionStep()
        schema_data = await gql_step.run(traces)
        type_count = len(schema_data.registry.types)
        enum_count = len(schema_data.registry.enums)
        ctx.on_progress(f"  Found {type_count} types, {enum_count} enums")

        # Phase B: Enrichment (optional)
        if not ctx.skip_enrich:
            enrich_step = GraphQLEnrichStep()
            try:
                ctx.on_progress("Enriching GraphQL schema (LLM)...")
                schema_data = await enrich_step.run(
                    GraphQLEnrichContext(
                        schema_data=schema_data,
                        traces=traces,
                        correlations=ctx.correlations,
                        app_name=ctx.app_name,
                    )
                )
            except Exception:
                pass  # keep unenriched schema

        # Phase C: Assembly
        ctx.on_progress("Assembling GraphQL SDL...")
        gql_assemble = GraphQLAssembleStep()
        sdl = await gql_assemble.run(schema_data)

        return BranchOutput(
            protocol=self.protocol,
            artifact=sdl,
            file_extension=self.file_extension,
            label=self.label,
        )
