"""GraphQL analysis pipeline: extract types -> enrich -> assemble SDL."""

from __future__ import annotations

from collections.abc import Callable

from cli.commands.capture.types import Trace
from cli.commands.graphql.analyze.assemble import assemble_graphql
from cli.commands.graphql.analyze.enrich import enrich_graphql
from cli.commands.graphql.analyze.extraction import extract_graphql
from cli.helpers.correlator import Correlation


async def graphql_analyze(
    traces: list[Trace],
    app_name: str,
    correlations: list[Correlation],
    skip_enrich: bool,
    on_progress: Callable[[str], None],
) -> str:
    """Run the full GraphQL analysis pipeline and return an SDL string."""
    # Phase A: Extraction
    on_progress("Extracting GraphQL schema from traces...")
    schema_data = await extract_graphql(traces)
    type_count = len(schema_data.registry.types)
    enum_count = len(schema_data.registry.enums)
    on_progress(f"  Found {type_count} types, {enum_count} enums")

    # Phase B: Enrichment (optional)
    if not skip_enrich:
        try:
            on_progress("Enriching GraphQL schema (LLM)...")
            schema_data = await enrich_graphql(
                schema_data=schema_data,
                traces=traces,
                correlations=correlations,
                app_name=app_name,
            )
        except Exception:
            pass  # keep unenriched schema

    # Phase C: Assembly
    on_progress("Assembling GraphQL SDL...")
    sdl = assemble_graphql(schema_data)

    return sdl
