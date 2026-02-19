"""Tests for GraphQL query parsing."""

from __future__ import annotations

import json

from cli.commands.analyze.steps.graphql.parser import parse_graphql_traces
from tests.analyze.steps.graphql.conftest import batch_trace, gql_trace
from tests.conftest import make_trace


class TestParseSimpleQuery:
    def test_basic_query(self):
        ops = parse_graphql_traces(
            [gql_trace("query GetUser { user { id name } }")]
        )
        assert len(ops) == 1
        op = ops[0]
        assert op.type == "query"
        assert op.name == "GetUser"
        field_names = [f.name for f in op.fields]
        assert "user" in field_names

    def test_mutation(self):
        ops = parse_graphql_traces(
            [gql_trace("mutation CreateUser($name: String!) { createUser(name: $name) { id } }")]
        )
        assert len(ops) == 1
        assert ops[0].type == "mutation"
        assert ops[0].name == "CreateUser"

    def test_subscription(self):
        ops = parse_graphql_traces(
            [gql_trace("subscription OnMessage { messageAdded { id text } }")]
        )
        assert len(ops) == 1
        assert ops[0].type == "subscription"
        assert ops[0].name == "OnMessage"


class TestParseAnonymousQuery:
    def test_generates_name_from_root_fields(self):
        ops = parse_graphql_traces(
            [gql_trace("{ user { id } }")]
        )
        assert len(ops) == 1
        assert ops[0].name is not None
        assert "User" in ops[0].name

    def test_multiple_root_fields(self):
        ops = parse_graphql_traces(
            [gql_trace("{ user { id } posts { title } }")]
        )
        assert len(ops) == 1
        assert ops[0].name is not None
        assert "User" in ops[0].name
        assert "Posts" in ops[0].name


class TestParseVariables:
    def test_variable_declarations(self):
        ops = parse_graphql_traces(
            [
                gql_trace(
                    "query GetUser($id: ID!, $limit: Int = 10) { user(id: $id) { name } }",
                    variables={"id": "123", "limit": 5},
                )
            ]
        )
        assert len(ops) == 1
        vars_ = ops[0].variables
        assert len(vars_) == 2
        id_var = next(v for v in vars_ if v.name == "id")
        assert id_var.type_name == "ID!"
        assert id_var.observed_value == "123"
        limit_var = next(v for v in vars_ if v.name == "limit")
        assert limit_var.type_name == "Int"
        assert limit_var.default_value == 10
        assert limit_var.observed_value == 5


class TestParseFragments:
    def test_fragment_spread_is_inlined(self):
        query = """
            query GetUser {
                user {
                    ...UserFields
                }
            }
            fragment UserFields on User {
                id
                name
                email
            }
        """
        ops = parse_graphql_traces([gql_trace(query)])
        assert len(ops) == 1
        # The user field should have children from the fragment
        user_field = next(f for f in ops[0].fields if f.name == "user")
        child_names = {c.name for c in user_field.children}
        assert {"id", "name", "email"} <= child_names
        # Fragment fields should carry the type condition
        for child in user_field.children:
            if child.name in ("id", "name", "email"):
                assert child.type_condition == "User"

    def test_fragment_names_collected(self):
        query = """
            query GetUser {
                user { ...UserFields }
            }
            fragment UserFields on User { id name }
        """
        ops = parse_graphql_traces([gql_trace(query)])
        assert "UserFields" in ops[0].fragment_names


class TestParseInlineFragments:
    def test_inline_fragment_type_condition(self):
        query = """
            query GetNode {
                node(id: "1") {
                    ... on User { name }
                    ... on Post { title }
                }
            }
        """
        ops = parse_graphql_traces([gql_trace(query)])
        node_field = next(f for f in ops[0].fields if f.name == "node")
        children = node_field.children
        user_children = [c for c in children if c.type_condition == "User"]
        post_children = [c for c in children if c.type_condition == "Post"]
        assert any(c.name == "name" for c in user_children)
        assert any(c.name == "title" for c in post_children)


class TestParseBatch:
    def test_batch_query(self):
        items = [
            {"query": "query A { user { id } }"},
            {"query": "query B { posts { title } }"},
        ]
        ops = parse_graphql_traces([batch_trace(items)])
        assert len(ops) == 2
        names = {op.name for op in ops}
        assert names == {"A", "B"}


class TestParsePersistedQueries:
    def test_persisted_query_skipped(self):
        """Traces with no 'query' field (persisted queries) are skipped."""
        trace = make_trace(
            trace_id="t_0001",
            method="POST",
            url="https://api.example.com/graphql",
            status=200,
            timestamp=1_000_000,
            request_body=json.dumps({
                "extensions": {"persistedQuery": {"sha256Hash": "abc123"}},
                "variables": {},
            }).encode(),
            response_body=b"{}",
        )
        ops = parse_graphql_traces([trace])
        assert len(ops) == 0

    def test_empty_query_skipped(self):
        ops = parse_graphql_traces(
            [gql_trace("")]
        )
        assert len(ops) == 0

    def test_invalid_query_skipped(self):
        ops = parse_graphql_traces(
            [gql_trace("this is not graphql")]
        )
        assert len(ops) == 0


class TestParseFieldArguments:
    def test_arguments_preserved(self):
        ops = parse_graphql_traces(
            [gql_trace('query { user(id: "123") { name } }')]
        )
        user_field = next(f for f in ops[0].fields if f.name == "user")
        assert "id" in user_field.arguments


class TestParseOperationName:
    def test_operation_name_selects_correct_op(self):
        query = """
            query GetUser { user { id } }
            query GetPosts { posts { title } }
        """
        ops = parse_graphql_traces(
            [gql_trace(query, operation_name="GetPosts")]
        )
        assert len(ops) == 1
        assert ops[0].name == "GetPosts"
