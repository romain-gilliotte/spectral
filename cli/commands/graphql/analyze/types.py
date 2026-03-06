"""GraphQL-specific types passed between pipeline steps.

Three layers of types:
1. Parsing output — one ParsedOperation per trace, representing the raw AST
2. Type registry — accumulates type information across all traces
3. Schema data — the final output combining all inferred types
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# -- Parsing output (one per trace) ------------------------------------------


@dataclass
class ParsedField:
    """A field in a GraphQL selection set."""

    name: str
    alias: str | None = None
    arguments: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    children: list[ParsedField] = field(default_factory=lambda: list[ParsedField]())
    type_condition: str | None = None  # from inline fragment (... on TypeName)


@dataclass
class ParsedVariable:
    """A declared variable in a GraphQL operation."""

    name: str  # without $
    type_name: str  # GraphQL type as string, e.g. "ID!", "[String]", "CreateUserInput!"
    default_value: Any = None
    observed_value: Any = None  # actual value from the JSON variables dict


@dataclass
class ParsedOperation:
    """A parsed GraphQL operation from a single trace."""

    type: str  # "query", "mutation", "subscription"
    name: str | None  # operation name (None for anonymous)
    variables: list[ParsedVariable] = field(default_factory=lambda: list[ParsedVariable]())
    fields: list[ParsedField] = field(default_factory=lambda: list[ParsedField]())
    raw_query: str = ""
    fragment_names: list[str] = field(default_factory=lambda: list[str]())


# -- Type registry (accumulated across traces) --------------------------------


@dataclass
class FieldRecord:
    """A field accumulated across multiple traces."""

    name: str
    type_name: str | None = None  # scalar name or reference to another type
    is_list: bool = False
    is_nullable: bool = True  # nullable by default, set to False when confirmed required
    is_always_present: bool = True  # tracks if field appeared in every response
    arguments: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    observed_values: list[Any] = field(default_factory=lambda: list[Any]())
    description: str | None = None  # LLM-inferred

    def add_observed(self, value: Any) -> None:
        """Add an observed value, keeping at most 5 distinct values."""
        if len(self.observed_values) < 5 and value not in self.observed_values:
            self.observed_values.append(value)


@dataclass
class EnumRecord:
    """An enum type inferred from variable values."""

    name: str
    values: set[str] = field(default_factory=lambda: set[str]())
    description: str | None = None  # LLM-inferred


@dataclass
class TypeRecord:
    """A GraphQL type being reconstructed from observations."""

    name: str
    kind: str = "object"  # "object", "input", "enum"
    fields: dict[str, FieldRecord] = field(default_factory=lambda: dict[str, FieldRecord]())
    interfaces: set[str] = field(default_factory=lambda: set[str]())
    observed_paths: list[str] = field(default_factory=lambda: list[str]())
    description: str | None = None  # LLM-inferred
    observation_count: int = 0  # how many times this type was seen


@dataclass
class TypeRegistry:
    """Central registry of all discovered types, keyed by type name."""

    types: dict[str, TypeRecord] = field(default_factory=lambda: dict[str, TypeRecord]())
    enums: dict[str, EnumRecord] = field(default_factory=lambda: dict[str, EnumRecord]())

    def get_or_create_type(self, name: str, kind: str = "object") -> TypeRecord:
        """Get an existing type or create a new one."""
        if name not in self.types:
            self.types[name] = TypeRecord(name=name, kind=kind)
        return self.types[name]

    def get_or_create_enum(self, name: str) -> EnumRecord:
        """Get an existing enum or create a new one."""
        if name not in self.enums:
            self.enums[name] = EnumRecord(name=name)
        return self.enums[name]


# -- Final output -------------------------------------------------------------


@dataclass
class GraphQLSchemaData:
    """Complete GraphQL schema reconstructed from captured traffic."""

    registry: TypeRegistry = field(default_factory=TypeRegistry)
    root_query_fields: list[str] = field(default_factory=lambda: list[str]())
    root_mutation_fields: list[str] = field(default_factory=lambda: list[str]())
    root_subscription_fields: list[str] = field(default_factory=lambda: list[str]())
