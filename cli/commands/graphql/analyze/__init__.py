"""GraphQL analysis pipeline: extract types -> enrich -> assemble SDL."""

from __future__ import annotations

from cli.commands.capture.types import Trace
from cli.commands.graphql.analyze.assemble import assemble_graphql
from cli.commands.graphql.analyze.enrich import enrich_graphql
from cli.commands.graphql.analyze.extraction import extract_graphql
from cli.helpers.console import console
from cli.helpers.correlator import Correlation


def graphql_analyze(
    traces: list[Trace],
    app_name: str,
    correlations: list[Correlation],
    skip_enrich: bool,
) -> str:
    """Run the full GraphQL analysis pipeline and return an SDL string."""
    # Phase A: Extraction
    console.print("  Extracting GraphQL schema from traces...")
    schema_data = extract_graphql(traces)
    type_count = len(schema_data.registry.types)
    enum_count = len(schema_data.registry.enums)
    console.print(f"    Found {type_count} types, {enum_count} enums")

    # Phase B: Enrichment (optional)
    if not skip_enrich:
        try:
            console.print("  Enriching GraphQL schema (LLM)...")
            schema_data = enrich_graphql(
                schema_data=schema_data,
                traces=traces,
                correlations=correlations,
                app_name=app_name,
            )
        except Exception:
            pass  # keep unenriched schema

    # Phase C: Assembly
    console.print("  Assembling GraphQL SDL...")
    sdl = assemble_graphql(schema_data)

    return sdl
