"""Step: Mechanical extraction of GraphQL schema from parsed operations + responses.

Walks the parsed query field tree and the JSON response data in parallel
to populate a TypeRegistry with inferred types, fields, scalars, enums,
and input types.
"""

from __future__ import annotations

import json
from typing import Any, cast

from cli.commands.analyze.steps.base import MechanicalStep
from cli.commands.analyze.steps.graphql.parser import parse_graphql_traces
from cli.commands.analyze.steps.graphql.types import (
    FieldRecord,
    GraphQLSchemaData,
    ParsedField,
    ParsedOperation,
    ParsedVariable,
    TypeRegistry,
)
from cli.commands.capture.types import Trace

# Mapping from JSON value types to GraphQL scalar names
_SCALAR_MAP: dict[str, str] = {
    "str": "String",
    "int": "Int",
    "float": "Float",
    "bool": "Boolean",
}


class GraphQLExtractionStep(MechanicalStep[list[Trace], GraphQLSchemaData]):
    """Build a GraphQL schema from captured traces using mechanical extraction.

    For each GraphQL trace:
    1. Parse the query from the request body
    2. Parse the JSON response body
    3. Walk the field tree + response in parallel to populate the TypeRegistry
    4. Infer input types and enums from query variables
    """

    name = "graphql_extraction"

    async def _execute(self, input: list[Trace]) -> GraphQLSchemaData:
        return extract_graphql_schema(input)


def extract_graphql_schema(traces: list[Trace]) -> GraphQLSchemaData:
    """Build a GraphQL schema from traces (synchronous entry point)."""
    registry = TypeRegistry()
    root_query_fields: set[str] = set()
    root_mutation_fields: set[str] = set()
    root_subscription_fields: set[str] = set()

    operations = parse_graphql_traces(traces)

    # Build a lookup from trace body hash to response body for matching
    trace_responses = _build_trace_response_map(traces)

    for op in operations:
        # Find the matching response by looking up the trace
        response_data = _find_response_for_operation(op, trace_responses)

        # Determine root type name
        root_type_name = _root_type_for_operation(op.type)

        # Track root fields
        for field in op.fields:
            if field.name == "__typename":
                continue
            if op.type == "query":
                root_query_fields.add(field.name)
            elif op.type == "mutation":
                root_mutation_fields.add(field.name)
            elif op.type == "subscription":
                root_subscription_fields.add(field.name)

        # Walk the field tree and response data to populate registry
        _walk_fields(
            registry=registry,
            fields=op.fields,
            response_data=response_data.get("data") if response_data else None,
            parent_type_name=root_type_name,
            parent_path=root_type_name,
        )

        # Process variables for input types and enums
        _process_variables(registry, op.variables)

    return GraphQLSchemaData(
        registry=registry,
        root_query_fields=sorted(root_query_fields),
        root_mutation_fields=sorted(root_mutation_fields),
        root_subscription_fields=sorted(root_subscription_fields),
    )


def _root_type_for_operation(op_type: str) -> str:
    """Map operation type to GraphQL root type name."""
    if op_type == "mutation":
        return "Mutation"
    if op_type == "subscription":
        return "Subscription"
    return "Query"


def _build_trace_response_map(
    traces: list[Trace],
) -> dict[str, dict[str, Any]]:
    """Build a map from request body content to parsed response data.

    Key is the raw request body string, value is parsed JSON response.
    """
    result: dict[str, dict[str, Any]] = {}
    for trace in traces:
        if not trace.request_body or not trace.response_body:
            continue
        try:
            key = trace.request_body.decode("utf-8", errors="replace")
            resp = json.loads(trace.response_body)
            if isinstance(resp, dict):
                result[key] = cast(dict[str, Any], resp)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return result


def _find_response_for_operation(
    op: ParsedOperation,
    trace_responses: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Find the response data matching an operation.

    Searches by matching the raw query string in request body keys.
    """
    for key, response in trace_responses.items():
        try:
            body = json.loads(key)
            if isinstance(body, dict) and cast(dict[str, Any], body).get("query") == op.raw_query:
                return response
            if isinstance(body, list):
                for item in cast(list[Any], body):
                    if isinstance(item, dict) and cast(dict[str, Any], item).get("query") == op.raw_query:
                        return response
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _walk_fields(
    registry: TypeRegistry,
    fields: list[ParsedField],
    response_data: Any,
    parent_type_name: str,
    parent_path: str,
) -> None:
    """Walk parsed fields and response data in parallel to populate the registry.

    For each field in the selection set:
    - Look up the corresponding value in the response
    - Infer the field type from the response value
    - If the value is an object, determine the type name and recurse
    """
    parent_type = registry.get_or_create_type(parent_type_name)
    parent_type.observation_count += 1

    if parent_path not in parent_type.observed_paths:
        parent_type.observed_paths.append(parent_path)

    if not isinstance(response_data, dict):
        response_data = {}

    resp_dict = cast(dict[str, Any], response_data)

    for field in fields:
        if field.name == "__typename":
            continue

        field_name = field.alias or field.name
        value: Any = resp_dict.get(field_name)

        # Get or create the field record
        field_rec = parent_type.fields.get(field.name)
        if field_rec is None:
            field_rec = FieldRecord(name=field.name)
            parent_type.fields[field.name] = field_rec

        # Copy arguments
        for arg_name, arg_type in field.arguments.items():
            if arg_name not in field_rec.arguments:
                field_rec.arguments[arg_name] = arg_type

        # Infer type from value
        if value is None:
            field_rec.is_nullable = True
        elif isinstance(value, list):
            field_rec.is_list = True
            _process_list_value(
                registry, field_rec, field, cast(list[Any], value), parent_path
            )
        elif isinstance(value, dict):
            child_dict = cast(dict[str, Any], value)
            type_name = _resolve_type_name(child_dict, field)
            field_rec.type_name = type_name
            _walk_fields(
                registry=registry,
                fields=field.children,
                response_data=child_dict,
                parent_type_name=type_name,
                parent_path=f"{parent_path}.{field.name}",
            )
        else:
            scalar = _infer_scalar(value)
            field_rec.type_name = scalar
            field_rec.add_observed(value)


def _process_list_value(
    registry: TypeRegistry,
    field_rec: FieldRecord,
    field: ParsedField,
    values: list[Any],
    parent_path: str,
) -> None:
    """Process a list value to infer item type."""
    for item in values[:5]:  # Sample first 5 items
        if isinstance(item, dict):
            child_dict = cast(dict[str, Any], item)
            type_name = _resolve_type_name(child_dict, field)
            field_rec.type_name = type_name
            _walk_fields(
                registry=registry,
                fields=field.children,
                response_data=child_dict,
                parent_type_name=type_name,
                parent_path=f"{parent_path}.{field.name}[]",
            )
            break  # Type name determined from first object item
        elif item is not None:
            field_rec.type_name = _infer_scalar(item)
            field_rec.add_observed(item)
            break


def _resolve_type_name(
    response_obj: dict[str, Any],
    field: ParsedField,
) -> str:
    """Determine the GraphQL type name for a response object.

    Priority:
    1. __typename from the response (guaranteed by __typename injection)
    2. Type condition from an inline fragment
    3. Generated from the field name (fallback for legacy bundles)
    """
    # 1. __typename from response
    typename = response_obj.get("__typename")
    if isinstance(typename, str) and typename:
        return typename

    # 2. Type condition from inline fragments on children
    if field.type_condition:
        return field.type_condition

    # Also check children for type conditions
    for child in field.children:
        if child.type_condition:
            return child.type_condition

    # 3. Fallback: generate from field name
    return _capitalize_field_name(field.name)


def _capitalize_field_name(name: str) -> str:
    """Convert a field name to a PascalCase type name.

    user -> User, orderItems -> OrderItems, my_field -> MyField
    """
    if not name:
        return "Unknown"
    # Handle snake_case
    if "_" in name:
        return "".join(part.capitalize() for part in name.split("_"))
    # Handle camelCase: just capitalize first letter
    return name[0].upper() + name[1:]


def _infer_scalar(value: Any) -> str:
    """Infer a GraphQL scalar type from a Python value."""
    type_name = type(value).__name__
    return _SCALAR_MAP.get(type_name, "String")


def _process_variables(
    registry: TypeRegistry,
    variables: list[ParsedVariable],
) -> None:
    """Process operation variables to detect input types and enums.

    For each variable:
    - If the observed value is a string -> could be an enum
    - If the observed value is an object -> input type
    - The GraphQL type annotation tells us the type name
    """
    for var in variables:
        observed: Any = var.observed_value
        if observed is None:
            continue

        # Extract the base type name (strip !, [], etc.)
        base_type = _strip_type_modifiers(var.type_name)

        # Skip built-in scalars
        if base_type in ("String", "Int", "Float", "Boolean", "ID"):
            continue

        if isinstance(observed, str):
            # String value for a non-scalar type -> enum
            enum_rec = registry.get_or_create_enum(base_type)
            enum_rec.values.add(observed)
        elif isinstance(observed, dict):
            # Object value -> input type
            _process_input_type(registry, base_type, cast(dict[str, Any], observed))
        elif isinstance(observed, list):
            # List value -> process items
            for item in cast(list[Any], observed):
                if isinstance(item, str):
                    # List of enum values
                    inner_type = _strip_type_modifiers(
                        var.type_name.lstrip("[").rstrip("]!").rstrip("]")
                    )
                    if inner_type not in ("String", "Int", "Float", "Boolean", "ID"):
                        enum_rec = registry.get_or_create_enum(inner_type)
                        enum_rec.values.add(item)
                elif isinstance(item, dict):
                    inner_type = _strip_type_modifiers(
                        var.type_name.lstrip("[").rstrip("]!").rstrip("]")
                    )
                    _process_input_type(registry, inner_type, cast(dict[str, Any], item))
                break  # Only need one item to determine type


def _process_input_type(
    registry: TypeRegistry,
    type_name: str,
    data: dict[str, Any],
) -> None:
    """Create or update an input type record from observed variable data."""
    type_rec = registry.get_or_create_type(type_name, kind="input")
    type_rec.kind = "input"
    type_rec.observation_count += 1

    for key, value in data.items():
        field_rec = type_rec.fields.get(key)
        if field_rec is None:
            field_rec = FieldRecord(name=key)
            type_rec.fields[key] = field_rec

        if value is None:
            field_rec.is_nullable = True
        elif isinstance(value, list):
            field_rec.is_list = True
            if value:
                field_rec.type_name = _infer_scalar(value[0])
        elif isinstance(value, dict):
            nested_name = _capitalize_field_name(key) + "Input"
            field_rec.type_name = nested_name
            _process_input_type(registry, nested_name, cast(dict[str, Any], value))
        else:
            field_rec.type_name = _infer_scalar(value)
            field_rec.add_observed(value)


def _strip_type_modifiers(type_str: str) -> str:
    """Strip GraphQL type modifiers (!, []) to get the base type name.

    Examples: "ID!" -> "ID", "[String!]!" -> "String", "CreateUserInput" -> "CreateUserInput"
    """
    result = type_str.strip()
    result = result.rstrip("!")
    if result.startswith("["):
        result = result[1:]
    result = result.rstrip("]").rstrip("!")
    return result
