"""Step: Enrich GraphQL types with business semantics via parallel per-type LLM calls."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from cli.commands.analyze.steps.base import Step
from cli.commands.analyze.steps.graphql.types import (
    GraphQLSchemaData,
    TypeRecord,
)
from cli.commands.analyze.steps.types import Correlation
from cli.commands.capture.types import Trace
from cli.helpers.console import console
import cli.helpers.llm as llm
from cli.helpers.llm import compact_json


class GraphQLEnrichContext:
    """Input for the GraphQL enrichment LLM step."""

    def __init__(
        self,
        schema_data: GraphQLSchemaData,
        traces: list[Trace],
        correlations: list[Correlation],
        app_name: str,
    ) -> None:
        self.schema_data = schema_data
        self.traces = traces
        self.correlations = correlations
        self.app_name = app_name


class GraphQLEnrichStep(Step[GraphQLEnrichContext, GraphQLSchemaData]):
    """Parallel per-type LLM calls to enrich each type with business descriptions.

    Each call receives:
    - Type name and list of fields with inferred types
    - Where this type appears in the schema (observed_paths)
    - Sample observed values per field

    The LLM returns a description for the type and each field.
    """

    name = "graphql_enrich"

    async def _execute(self, input: GraphQLEnrichContext) -> GraphQLSchemaData:
        registry = input.schema_data.registry

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
            prompt = f"""You are analyzing a GraphQL API discovered from "{input.app_name}".

Below is a type reconstructed from captured traffic. The "observed_values" show sample values
seen in real responses — use these to understand business meaning.

{compact_json(summary)}

Provide a JSON response:
{{
  "description": "What this type represents in business terms",
  "fields": {{
    "field_name": "What this field means in business terms",
    ...
  }}
}}

Respond in compact JSON only (no indentation)."""

            try:
                text = await llm.ask(prompt, max_tokens=1024, label=f"enrich_gql_{type_rec.name}")
                data = llm.extract_json(text)
                if isinstance(data, dict):
                    _apply_type_enrichment(type_rec, data)
            except Exception as exc:
                console.print(
                    f"  [red]GraphQL enrichment failed for {type_rec.name}: "
                    f"{type(exc).__name__}[/red]"
                )

        async def _enrich_enum(enum_name: str, enum_values: set[str]) -> None:
            values_list = sorted(enum_values)
            prompt = f"""You are analyzing a GraphQL API discovered from "{input.app_name}".

An enum type "{enum_name}" was found with these values: {compact_json(values_list)}

Provide a JSON response:
{{
  "description": "What this enum represents in business terms"
}}

Respond in compact JSON only (no indentation)."""

            try:
                text = await llm.ask(prompt, max_tokens=256, label=f"enrich_gql_enum_{enum_name}")
                data = llm.extract_json(text)
                if isinstance(data, dict):
                    desc = data.get("description")
                    if isinstance(desc, str):
                        registry.enums[enum_name].description = desc
            except Exception:
                pass

        tasks: list[Any] = [_enrich_type(t) for t in types_to_enrich]
        tasks.extend(_enrich_enum(e.name, e.values) for e in enums_to_enrich)
        await asyncio.gather(*tasks)

        return input.schema_data


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


def _apply_type_enrichment(type_rec: TypeRecord, data: dict[str, Any]) -> None:
    """Apply LLM enrichment to a type record."""
    desc = data.get("description")
    if isinstance(desc, str):
        type_rec.description = desc

    raw_field_descs: Any = data.get("fields", {})
    if isinstance(raw_field_descs, dict):
        field_descs: dict[str, Any] = cast(dict[str, Any], raw_field_descs)
        for field_name, field_desc in field_descs.items():
            if isinstance(field_desc, str) and field_name in type_rec.fields:
                type_rec.fields[field_name].description = field_desc
