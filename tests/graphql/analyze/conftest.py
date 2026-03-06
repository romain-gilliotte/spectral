"""Shared helpers for GraphQL test files."""

from __future__ import annotations

import json
from typing import Any

from cli.commands.capture.types import Trace
from tests.conftest import make_trace


def gql_trace(
    query: str,
    response_data: dict[str, Any] | list[Any] | None = None,
    variables: dict[str, Any] | None = None,
    operation_name: str | None = None,
    trace_id: str = "t_0001",
    url: str = "https://api.example.com/graphql",
) -> Trace:
    """Build a Trace carrying a GraphQL request/response pair."""
    body: dict[str, Any] = {"query": query}
    if variables is not None:
        body["variables"] = variables
    if operation_name is not None:
        body["operationName"] = operation_name
    resp: dict[str, Any] = {"data": response_data} if response_data is not None else {}
    return make_trace(
        trace_id=trace_id,
        method="POST",
        url=url,
        status=200,
        timestamp=1_000_000,
        request_body=json.dumps(body).encode(),
        response_body=json.dumps(resp).encode(),
    )


def batch_trace(
    items: list[dict[str, Any]],
    response_data: list[dict[str, Any]] | None = None,
    trace_id: str = "t_0001",
) -> Trace:
    """Build a Trace carrying a batch GraphQL request."""
    return make_trace(
        trace_id=trace_id,
        method="POST",
        url="https://api.example.com/graphql",
        status=200,
        timestamp=1_000_000,
        request_body=json.dumps(items).encode(),
        response_body=json.dumps(response_data or []).encode(),
    )
