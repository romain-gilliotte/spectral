"""Parse GraphQL queries from captured trace request bodies.

Uses graphql-core to parse query strings into a structured AST, then
extracts operations, fields, variables, and fragments into our internal
ParsedOperation representation.
"""

from __future__ import annotations

import json
from typing import Any, cast

from graphql import parse as gql_parse
from graphql.error import GraphQLSyntaxError
from graphql.language import print_ast
from graphql.language.ast import (
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    InlineFragmentNode,
    OperationDefinitionNode,
    SelectionSetNode,
)

from cli.commands.analyze.steps.graphql.types import (
    ParsedField,
    ParsedOperation,
    ParsedVariable,
)
from cli.commands.capture.types import Trace


def parse_graphql_traces(traces: list[Trace]) -> list[ParsedOperation]:
    """Parse all GraphQL traces and return a list of parsed operations.

    Each trace may contain a single query or a batch of queries.
    Persisted queries (no ``query`` field) are skipped.
    """
    operations: list[ParsedOperation] = []
    for trace in traces:
        if not trace.request_body:
            continue
        try:
            body = json.loads(trace.request_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        # Handle batch queries: [{query: ...}, {query: ...}]
        if isinstance(body, list):
            for item in cast(list[Any], body):
                if isinstance(item, dict):
                    ops = _parse_single_body(cast(dict[str, Any], item))
                    operations.extend(ops)
        elif isinstance(body, dict):
            ops = _parse_single_body(cast(dict[str, Any], body))
            operations.extend(ops)

    return operations


def _parse_single_body(body: dict[str, Any]) -> list[ParsedOperation]:
    """Parse a single GraphQL request body dict into operations.

    Returns empty list for persisted queries (no ``query`` field) or
    unparseable queries.
    """
    query_str = body.get("query")
    if not isinstance(query_str, str) or not query_str.strip():
        return []

    try:
        document = gql_parse(query_str)
    except GraphQLSyntaxError:
        return []

    raw_variables: Any = body.get("variables") or {}
    variables_json: dict[str, Any] = cast(dict[str, Any], raw_variables) if isinstance(raw_variables, dict) else {}
    operation_name: str | None = body.get("operationName")

    # Collect fragment definitions for resolution
    fragments: dict[str, FragmentDefinitionNode] = {}
    for defn in document.definitions:
        if isinstance(defn, FragmentDefinitionNode):
            fragments[defn.name.value] = defn

    operations: list[ParsedOperation] = []
    for defn in document.definitions:
        if not isinstance(defn, OperationDefinitionNode):
            continue
        # If operationName is specified, only parse the matching operation
        if operation_name and defn.name and defn.name.value != operation_name:
            continue

        op = _build_operation(defn, fragments, variables_json, query_str)
        operations.append(op)

    return operations


def _build_operation(
    node: OperationDefinitionNode,
    fragments: dict[str, FragmentDefinitionNode],
    variables_json: dict[str, Any],
    raw_query: str,
) -> ParsedOperation:
    """Build a ParsedOperation from an OperationDefinitionNode."""
    op_type = node.operation.value  # "query", "mutation", "subscription"
    op_name = node.name.value if node.name else None

    # Parse variables
    parsed_vars: list[ParsedVariable] = []
    for var_def in node.variable_definitions or []:
        var_name = var_def.variable.name.value
        var_type = print_ast(var_def.type)
        default = None
        if var_def.default_value is not None:
            default = _ast_value_to_python(var_def.default_value)
        observed = variables_json.get(var_name)
        parsed_vars.append(
            ParsedVariable(
                name=var_name,
                type_name=var_type,
                default_value=default,
                observed_value=observed,
            )
        )

    # Parse selection set
    fields = _parse_selection_set(node.selection_set, fragments)

    # Collect referenced fragment names
    fragment_names = _collect_fragment_refs(node.selection_set)

    # Generate name for anonymous queries
    if op_name is None and fields:
        op_name = _generate_anonymous_name(op_type, fields)

    return ParsedOperation(
        type=op_type,
        name=op_name,
        variables=parsed_vars,
        fields=fields,
        raw_query=raw_query,
        fragment_names=fragment_names,
    )


def _parse_selection_set(
    selection_set: SelectionSetNode | None,
    fragments: dict[str, FragmentDefinitionNode],
) -> list[ParsedField]:
    """Parse a selection set into a list of ParsedField, resolving fragments."""
    if not selection_set:
        return []

    fields: list[ParsedField] = []
    for selection in selection_set.selections:
        if isinstance(selection, FieldNode):
            args: dict[str, str] = {}
            for arg in selection.arguments or []:
                args[arg.name.value] = print_ast(arg.value)
            children = _parse_selection_set(selection.selection_set, fragments)
            fields.append(
                ParsedField(
                    name=selection.name.value,
                    alias=selection.alias.value if selection.alias else None,
                    arguments=args,
                    children=children,
                )
            )
        elif isinstance(selection, FragmentSpreadNode):
            # Resolve fragment: inline its fields
            frag_name = selection.name.value
            frag_def = fragments.get(frag_name)
            if frag_def and frag_def.selection_set:
                frag_fields = _parse_selection_set(frag_def.selection_set, fragments)
                # Tag with fragment type condition
                type_cond = frag_def.type_condition.name.value
                for f in frag_fields:
                    if f.type_condition is None:
                        f.type_condition = type_cond
                fields.extend(frag_fields)
        elif isinstance(selection, InlineFragmentNode):
            type_cond = (
                selection.type_condition.name.value
                if selection.type_condition
                else None
            )
            inline_fields = _parse_selection_set(selection.selection_set, fragments)
            for f in inline_fields:
                if f.type_condition is None:
                    f.type_condition = type_cond
            fields.extend(inline_fields)

    return fields


def _collect_fragment_refs(selection_set: SelectionSetNode | None) -> list[str]:
    """Recursively collect all fragment spread names from a selection set."""
    if not selection_set:
        return []
    names: list[str] = []
    for selection in selection_set.selections:
        if isinstance(selection, FragmentSpreadNode):
            names.append(selection.name.value)
        elif isinstance(selection, (FieldNode, InlineFragmentNode)):
            sel_set = getattr(selection, "selection_set", None)
            if sel_set:
                names.extend(_collect_fragment_refs(sel_set))
    return names


def _generate_anonymous_name(op_type: str, fields: list[ParsedField]) -> str:
    """Generate a name for anonymous operations from root field names."""
    root_names = [f.name for f in fields if f.name != "__typename"][:3]
    if root_names:
        parts = "_".join(n.capitalize() for n in root_names)
        return f"Anonymous{op_type.capitalize()}_{parts}"
    return f"Anonymous{op_type.capitalize()}"


def _ast_value_to_python(node: Any) -> Any:
    """Convert a graphql-core AST value node to a Python value."""
    from graphql.language.ast import (
        BooleanValueNode,
        EnumValueNode,
        FloatValueNode,
        IntValueNode,
        ListValueNode,
        NullValueNode,
        ObjectValueNode,
        StringValueNode,
    )

    if isinstance(node, StringValueNode):
        return node.value
    if isinstance(node, IntValueNode):
        return int(node.value)
    if isinstance(node, FloatValueNode):
        return float(node.value)
    if isinstance(node, BooleanValueNode):
        return node.value
    if isinstance(node, NullValueNode):
        return None
    if isinstance(node, EnumValueNode):
        return node.value
    if isinstance(node, ListValueNode):
        return [_ast_value_to_python(v) for v in node.values]
    if isinstance(node, ObjectValueNode):
        return {f.name.value: _ast_value_to_python(f.value) for f in node.fields}
    return str(node)
