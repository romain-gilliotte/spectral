"""GraphQL __typename injection for the MITM proxy.

Injects ``__typename`` into all selection sets of a GraphQL query.
This ensures response objects carry their type names, which is needed
for accurate type inference during analysis.

Also provides ``inject_typename_into_flow`` which operates on a
mitmproxy ``HTTPFlow``, detecting JSON bodies that look like GraphQL.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from graphql import parse as gql_parse, print_ast
from graphql.error import GraphQLSyntaxError
from graphql.language.ast import (
    FieldNode,
    NameNode,
    SelectionSetNode,
)
from graphql.language.visitor import Visitor, visit

if TYPE_CHECKING:
    from mitmproxy.http import HTTPFlow


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


def inject_typename_into_flow(flow: HTTPFlow) -> None:
    """Inject __typename into GraphQL query bodies in a mitmproxy flow.

    Checks body shape (JSON with a ``query`` string field) and delegates
    to the graphql-core parser via ``inject_typename()`` which returns
    the query unchanged if it is not valid GraphQL.
    """
    req = flow.request
    if req.method.upper() != "POST":
        return

    content_type = str(req.headers.get("content-type", "") or "")  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    if "json" not in content_type.lower():
        return

    body_bytes = req.content
    if not body_bytes:
        return

    try:
        body: Any = json.loads(body_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    if isinstance(body, dict):
        if _inject_typename_in_body(cast(dict[str, object], body)):
            req.content = json.dumps(body).encode()
    elif isinstance(body, list):
        # Batch GraphQL
        modified = False
        for item in cast(list[Any], body):
            if isinstance(item, dict) and _inject_typename_in_body(
                cast(dict[str, object], item)
            ):
                modified = True
        if modified:
            req.content = json.dumps(body).encode()


def _inject_typename_in_body(body: dict[str, object]) -> bool:
    """Inject __typename into a single GraphQL body dict. Returns True if modified."""
    query = body.get("query")
    if not isinstance(query, str):
        return False

    modified_query = inject_typename(query)
    if modified_query != query:
        body["query"] = modified_query
        return True
    return False
