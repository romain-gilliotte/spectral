"""Step: Assemble a GraphQL SDL string from the inferred schema data."""

from __future__ import annotations

from cli.commands.analyze.steps.base import MechanicalStep
from cli.commands.analyze.steps.graphql.types import (
    EnumRecord,
    FieldRecord,
    GraphQLSchemaData,
    TypeRecord,
    TypeRegistry,
)


class GraphQLAssembleStep(MechanicalStep[GraphQLSchemaData, str]):
    """Generate a GraphQL SDL string from the inferred schema data."""

    name = "graphql_assemble"

    async def _execute(self, input: GraphQLSchemaData) -> str:
        return build_sdl(input)


def build_sdl(schema_data: GraphQLSchemaData) -> str:
    """Build a complete GraphQL SDL string from schema data."""
    registry = schema_data.registry
    parts: list[str] = []

    # Root types
    for root_name, root_fields in [
        ("Query", schema_data.root_query_fields),
        ("Mutation", schema_data.root_mutation_fields),
        ("Subscription", schema_data.root_subscription_fields),
    ]:
        if not root_fields:
            continue
        root_type = registry.types.get(root_name)
        if root_type:
            parts.append(_render_type(root_type, root_fields))

    # Object types (non-root, non-input)
    for type_rec in _sorted_types(registry):
        if type_rec.name in ("Query", "Mutation", "Subscription"):
            continue
        if type_rec.kind == "input":
            continue
        if not type_rec.fields:
            continue
        parts.append(_render_type(type_rec))

    # Input types
    for type_rec in _sorted_types(registry):
        if type_rec.kind != "input":
            continue
        if not type_rec.fields:
            continue
        parts.append(_render_input_type(type_rec))

    # Enums
    for enum_rec in _sorted_enums(registry):
        if not enum_rec.values:
            continue
        parts.append(_render_enum(enum_rec))

    return "\n\n".join(parts) + "\n" if parts else ""


def _sorted_types(registry: TypeRegistry) -> list[TypeRecord]:
    """Return type records sorted by name."""
    return sorted(registry.types.values(), key=lambda t: t.name)


def _sorted_enums(registry: TypeRegistry) -> list[EnumRecord]:
    """Return enum records sorted by name."""
    return sorted(registry.enums.values(), key=lambda e: e.name)


def _render_type(
    type_rec: TypeRecord,
    field_order: list[str] | None = None,
) -> str:
    """Render an object type to SDL."""
    lines: list[str] = []

    # Type description
    if type_rec.description:
        lines.append(f'"""{_escape_description(type_rec.description)}"""')

    # Type declaration with interfaces
    decl = f"type {type_rec.name}"
    if type_rec.interfaces:
        implements = " & ".join(sorted(type_rec.interfaces))
        decl += f" implements {implements}"
    lines.append(f"{decl} {{")

    # Fields — use field_order if provided, otherwise sort by name
    if field_order:
        ordered_fields = [
            type_rec.fields[name]
            for name in field_order
            if name in type_rec.fields
        ]
        # Also add any fields not in field_order
        ordered_names = set(field_order)
        for name in sorted(type_rec.fields):
            if name not in ordered_names:
                ordered_fields.append(type_rec.fields[name])
    else:
        ordered_fields = sorted(type_rec.fields.values(), key=lambda f: f.name)

    for field_rec in ordered_fields:
        lines.append(_render_field(field_rec))

    lines.append("}")
    return "\n".join(lines)


def _render_input_type(type_rec: TypeRecord) -> str:
    """Render an input type to SDL."""
    lines: list[str] = []

    if type_rec.description:
        lines.append(f'"""{_escape_description(type_rec.description)}"""')

    lines.append(f"input {type_rec.name} {{")
    for field_rec in sorted(type_rec.fields.values(), key=lambda f: f.name):
        lines.append(_render_field(field_rec))
    lines.append("}")
    return "\n".join(lines)


def _render_enum(enum_rec: EnumRecord) -> str:
    """Render an enum type to SDL."""
    lines: list[str] = []

    if enum_rec.description:
        lines.append(f'"""{_escape_description(enum_rec.description)}"""')

    lines.append(f"enum {enum_rec.name} {{")
    for value in sorted(enum_rec.values):
        lines.append(f"  {value}")
    lines.append("}")
    return "\n".join(lines)


def _render_field(field_rec: FieldRecord) -> str:
    """Render a single field line with optional description, arguments, and type."""
    parts: list[str] = []

    # Field description
    if field_rec.description:
        parts.append(f'  """{_escape_description(field_rec.description)}"""')

    # Field name + arguments + type
    field_line = f"  {field_rec.name}"

    # Arguments
    if field_rec.arguments:
        args = ", ".join(
            f"{arg_name}: {arg_type}"
            for arg_name, arg_type in sorted(field_rec.arguments.items())
        )
        field_line += f"({args})"

    # Type
    type_str = _format_field_type(field_rec)
    field_line += f": {type_str}"

    parts.append(field_line)
    return "\n".join(parts)


def _format_field_type(field_rec: FieldRecord) -> str:
    """Format the GraphQL type string for a field.

    Rules:
    - If always present and never null -> non-nullable (!)
    - If list -> [Type] or [Type!]!
    - Otherwise -> nullable (no !)
    """
    base = field_rec.type_name or "String"

    if field_rec.is_list:
        # For lists, the inner type is non-nullable if we never saw null items
        inner = f"{base}!"
        if field_rec.is_nullable:
            return f"[{inner}]"
        return f"[{inner}]!"

    if not field_rec.is_nullable and field_rec.is_always_present:
        return f"{base}!"

    return base


def _escape_description(text: str) -> str:
    """Escape a description string for use in triple-quoted SDL strings."""
    return text.replace('"""', '\\"\\"\\"')
