"""Tests for GraphQL end-to-end integration: parse → extract → assemble."""

from __future__ import annotations

import json

from cli.commands.analyze.steps.graphql.assemble import build_sdl
from cli.commands.analyze.steps.graphql.extraction import extract_graphql_schema
from tests.analyze.steps.graphql.conftest import gql_trace
from tests.conftest import make_trace


class TestEndToEnd:
    def test_full_pipeline(self):
        """Parse traces, extract schema, assemble SDL — full round trip."""
        traces = [
            gql_trace(
                query="""
                    query GetUser($id: ID!) {
                        user(id: $id) {
                            id
                            name
                            email
                            orders {
                                id
                                total
                                status
                            }
                        }
                    }
                """,
                variables={"id": "user-123"},
                response_data={
                    "user": {
                        "__typename": "User",
                        "id": "user-123",
                        "name": "Alice",
                        "email": "alice@example.com",
                        "orders": [
                            {
                                "__typename": "Order",
                                "id": "order-1",
                                "total": 42.50,
                                "status": "SHIPPED",
                            },
                            {
                                "__typename": "Order",
                                "id": "order-2",
                                "total": 99.00,
                                "status": "PENDING",
                            },
                        ],
                    }
                },
                trace_id="t_0001",
            ),
            gql_trace(
                query="""
                    mutation CreateOrder($input: CreateOrderInput!) {
                        createOrder(input: $input) {
                            id
                            total
                        }
                    }
                """,
                variables={"input": {"productId": "p-1", "quantity": 3}},
                response_data={
                    "createOrder": {
                        "__typename": "Order",
                        "id": "order-3",
                        "total": 75.00,
                    }
                },
                trace_id="t_0002",
            ),
        ]

        schema = extract_graphql_schema(traces)

        # Verify extraction
        assert "user" in schema.root_query_fields
        assert "createOrder" in schema.root_mutation_fields
        assert "User" in schema.registry.types
        assert "Order" in schema.registry.types
        assert "CreateOrderInput" in schema.registry.types

        # Verify User fields
        user_type = schema.registry.types["User"]
        assert {"id", "name", "email", "orders"} <= set(user_type.fields.keys())
        assert user_type.fields["orders"].is_list is True
        assert user_type.fields["orders"].type_name == "Order"

        # Verify Order fields
        order_type = schema.registry.types["Order"]
        assert {"id", "total", "status"} <= set(order_type.fields.keys())
        assert order_type.fields["total"].type_name == "Float"

        # Verify input type
        input_type = schema.registry.types["CreateOrderInput"]
        assert input_type.kind == "input"
        assert "productId" in input_type.fields
        assert "quantity" in input_type.fields

        # Assemble SDL
        sdl = build_sdl(schema)
        assert "type Query" in sdl
        assert "type Mutation" in sdl
        assert "type User" in sdl
        assert "type Order" in sdl
        assert "input CreateOrderInput" in sdl

    def test_no_response_body(self):
        """Traces with no response should still parse queries."""
        trace = make_trace(
            trace_id="t_0001",
            method="POST",
            url="https://api.example.com/graphql",
            status=200,
            timestamp=1_000_000,
            request_body=json.dumps({
                "query": "query { user { id } }",
            }).encode(),
            response_body=b"",
        )
        schema = extract_graphql_schema([trace])
        # Query should still be parsed and root fields tracked
        assert "user" in schema.root_query_fields

    def test_non_json_body_skipped(self):
        """Traces with non-JSON bodies should be gracefully skipped."""
        trace = make_trace(
            trace_id="t_0001",
            method="POST",
            url="https://api.example.com/graphql",
            status=200,
            timestamp=1_000_000,
            request_body=b"not json at all",
            response_body=b"also not json",
        )
        schema = extract_graphql_schema([trace])
        assert len(schema.root_query_fields) == 0
