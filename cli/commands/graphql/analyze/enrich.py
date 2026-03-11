"""Enrich GraphQL types with business semantics via parallel per-type LLM calls."""

from __future__ import annotations

import asyncio
from typing import Any

from cli.commands.capture.types import Trace
from cli.commands.graphql.analyze.types import (
    EnumEnrichmentResponse,
    GraphQLSchemaData,
    TypeEnrichmentResponse,
    TypeRecord,
)
from cli.helpers.console import console
from cli.helpers.correlator import Correlation
import cli.helpers.llm as llm
from cli.helpers.prompt import render


async def enrich_graphql(
    schema_data: GraphQLSchemaData,
    traces: list[Trace],
    correlations: list[Correlation],
    app_name: str,
) -> GraphQLSchemaData:
    """Parallel per-type LLM calls to enrich each type with business descriptions.

    Each call receives:
    - Type name and list of fields with inferred types
    - Where this type appears in the schema (observed_paths)
    - Sample observed values per field

    The LLM returns a description for the type and each field.
    """
    registry = schema_data.registry

    # Collect types worth enriching (skip root types, enrich their fields via subtypes)
    types_to_enrich = [
        t for t in registry.types.values()
        if t.name not in ("Query", "Mutation", "Subscription")
        and t.fields
    ]

    # Also enrich root types for operation descriptions
    root_types = [
        t for t in registry.types.values()
        if t.name in ("Query", "Mutation", "Subscription")
        and t.fields
    ]
    types_to_enrich.extend(root_types)

    # Enrich enums too
    enums_to_enrich = [e for e in registry.enums.values() if e.values]

    async def _enrich_type(type_rec: TypeRecord) -> None:
        summary = _build_type_summary(type_rec)
        prompt = render(
            "graphql-enrich-type.j2",
            app_name=app_name,
            summary=summary,
        )

        try:
            conv = llm.Conversation(max_tokens=1024, label=f"enrich_gql_{type_rec.name}")
            result = await conv.ask_json(prompt, TypeEnrichmentResponse)
            _apply_type_enrichment(type_rec, result)
        except Exception as exc:
            console.print(
                f"  [red]GraphQL enrichment failed for {type_rec.name}: "
                f"{type(exc).__name__}[/red]"
            )

    async def _enrich_enum(enum_name: str, enum_values: set[str]) -> None:
        values = sorted(enum_values)
        prompt = render(
            "graphql-enrich-enum.j2",
            app_name=app_name,
            enum_name=enum_name,
            values=values,
        )

        try:
            conv = llm.Conversation(max_tokens=256, label=f"enrich_gql_enum_{enum_name}")
            result = await conv.ask_json(prompt, EnumEnrichmentResponse)
            registry.enums[enum_name].description = result.description
        except Exception:
            pass

    tasks: list[Any] = [_enrich_type(t) for t in types_to_enrich]
    tasks.extend(_enrich_enum(e.name, e.values) for e in enums_to_enrich)
    await asyncio.gather(*tasks)

    return schema_data


def _build_type_summary(type_rec: TypeRecord) -> dict[str, Any]:
    """Build a summary of a type for the LLM prompt."""
    summary: dict[str, Any] = {
        "type_name": type_rec.name,
        "kind": type_rec.kind,
    }

    if type_rec.observed_paths:
        summary["appears_at"] = type_rec.observed_paths[:5]

    if type_rec.interfaces:
        summary["implements"] = sorted(type_rec.interfaces)

    fields_summary: dict[str, Any] = {}
    for field_name, field_rec in type_rec.fields.items():
        field_info: dict[str, Any] = {}
        if field_rec.type_name:
            type_str = field_rec.type_name
            if field_rec.is_list:
                type_str = f"[{type_str}]"
            if not field_rec.is_nullable:
                type_str += "!"
            field_info["type"] = type_str
        if field_rec.arguments:
            field_info["arguments"] = field_rec.arguments
        if field_rec.observed_values:
            field_info["observed_values"] = field_rec.observed_values
        fields_summary[field_name] = field_info

    summary["fields"] = fields_summary
    return summary


def _apply_type_enrichment(type_rec: TypeRecord, data: TypeEnrichmentResponse) -> None:
    """Apply LLM enrichment to a type record."""
    type_rec.description = data.description

    for field_name, field_desc in data.fields.items():
        if field_name in type_rec.fields:
            type_rec.fields[field_name].description = field_desc
