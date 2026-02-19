"""GraphQL query utilities for __typename injection.

Injects ``__typename`` into all selection sets of a GraphQL query.
This ensures response objects carry their type names, which is needed
for accurate type inference during analysis.
"""

from __future__ import annotations

from graphql import parse as gql_parse, print_ast
from graphql.error import GraphQLSyntaxError
from graphql.language.ast import (
    FieldNode,
    NameNode,
    SelectionSetNode,
)
from graphql.language.visitor import Visitor, visit


class _TypenameInjector(Visitor):
    """AST visitor that adds ``__typename`` to every selection set."""

    def enter_selection_set(
        self,
        node: SelectionSetNode,
        *_args: object,
    ) -> SelectionSetNode:
        # Check if __typename is already present
        for sel in node.selections:
            if isinstance(sel, FieldNode) and sel.name.value == "__typename":
                return node

        typename_field = FieldNode(name=NameNode(value="__typename"))
        new_selections = (*node.selections, typename_field)
        return SelectionSetNode(selections=new_selections)


def inject_typename(query_str: str) -> str:
    """Inject ``__typename`` into every selection set of a GraphQL query.

    If the query cannot be parsed, returns it unchanged.

    >>> inject_typename("{ user { name } }")
    '{\\n  user {\\n    name\\n    __typename\\n  }\\n  __typename\\n}'
    """
    try:
        doc = gql_parse(query_str)
    except GraphQLSyntaxError:
        return query_str

    modified = visit(doc, _TypenameInjector())
    return print_ast(modified)
