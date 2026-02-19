"""Tests for the GraphQL analysis pipeline: parsing, extraction, assembly, and __typename injection."""

from __future__ import annotations

import json
from typing import Any

import pytest

from cli.commands.analyze.steps.graphql.assemble import build_sdl
from cli.commands.analyze.steps.graphql.extraction import (
    _capitalize_field_name,  # pyright: ignore[reportPrivateUsage]
    _infer_scalar,  # pyright: ignore[reportPrivateUsage]
    _strip_type_modifiers,  # pyright: ignore[reportPrivateUsage]
    extract_graphql_schema,
)
from cli.commands.analyze.steps.graphql.parser import parse_graphql_traces
from cli.commands.analyze.steps.graphql.types import (
    EnumRecord,
    FieldRecord,
    GraphQLSchemaData,
    TypeRegistry,
)
from cli.commands.capture.graphql_utils import inject_typename
from cli.commands.capture.types import Trace
from tests.conftest import make_trace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gql_trace(
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


def _batch_trace(
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


# ===========================================================================
# 1. Parser tests
# ===========================================================================


class TestParseSimpleQuery:
    def test_basic_query(self):
        ops = parse_graphql_traces(
            [_gql_trace("query GetUser { user { id name } }")]
        )
        assert len(ops) == 1
        op = ops[0]
        assert op.type == "query"
        assert op.name == "GetUser"
        field_names = [f.name for f in op.fields]
        assert "user" in field_names

    def test_mutation(self):
        ops = parse_graphql_traces(
            [_gql_trace("mutation CreateUser($name: String!) { createUser(name: $name) { id } }")]
        )
        assert len(ops) == 1
        assert ops[0].type == "mutation"
        assert ops[0].name == "CreateUser"

    def test_subscription(self):
        ops = parse_graphql_traces(
            [_gql_trace("subscription OnMessage { messageAdded { id text } }")]
        )
        assert len(ops) == 1
        assert ops[0].type == "subscription"
        assert ops[0].name == "OnMessage"


class TestParseAnonymousQuery:
    def test_generates_name_from_root_fields(self):
        ops = parse_graphql_traces(
            [_gql_trace("{ user { id } }")]
        )
        assert len(ops) == 1
        assert ops[0].name is not None
        assert "User" in ops[0].name

    def test_multiple_root_fields(self):
        ops = parse_graphql_traces(
            [_gql_trace("{ user { id } posts { title } }")]
        )
        assert len(ops) == 1
        assert ops[0].name is not None
        assert "User" in ops[0].name
        assert "Posts" in ops[0].name


class TestParseVariables:
    def test_variable_declarations(self):
        ops = parse_graphql_traces(
            [
                _gql_trace(
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
        ops = parse_graphql_traces([_gql_trace(query)])
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
        ops = parse_graphql_traces([_gql_trace(query)])
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
        ops = parse_graphql_traces([_gql_trace(query)])
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
        ops = parse_graphql_traces([_batch_trace(items)])
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
            [_gql_trace("")]
        )
        assert len(ops) == 0

    def test_invalid_query_skipped(self):
        ops = parse_graphql_traces(
            [_gql_trace("this is not graphql")]
        )
        assert len(ops) == 0


class TestParseFieldArguments:
    def test_arguments_preserved(self):
        ops = parse_graphql_traces(
            [_gql_trace('query { user(id: "123") { name } }')]
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
            [_gql_trace(query, operation_name="GetPosts")]
        )
        assert len(ops) == 1
        assert ops[0].name == "GetPosts"


# ===========================================================================
# 2. Extraction tests
# ===========================================================================


class TestExtractSimple:
    def test_query_fields_tracked(self):
        traces = [
            _gql_trace(
                "query { user { id name } }",
                response_data={"user": {"id": "1", "name": "Alice", "__typename": "User"}},
            )
        ]
        schema = extract_graphql_schema(traces)
        assert "user" in schema.root_query_fields
        assert "User" in schema.registry.types
        user_type = schema.registry.types["User"]
        assert "id" in user_type.fields
        assert "name" in user_type.fields

    def test_mutation_fields_tracked(self):
        traces = [
            _gql_trace(
                "mutation { createUser(name: \"Bob\") { id } }",
                response_data={"createUser": {"id": "2", "__typename": "User"}},
            )
        ]
        schema = extract_graphql_schema(traces)
        assert "createUser" in schema.root_mutation_fields


class TestScalarInference:
    def test_string_inferred(self):
        assert _infer_scalar("hello") == "String"

    def test_int_inferred(self):
        assert _infer_scalar(42) == "Int"

    def test_float_inferred(self):
        assert _infer_scalar(3.14) == "Float"

    def test_bool_inferred(self):
        assert _infer_scalar(True) == "Boolean"

    def test_unknown_defaults_to_string(self):
        assert _infer_scalar(object()) == "String"


class TestTypeNaming:
    def test_typename_from_response(self):
        traces = [
            _gql_trace(
                "{ user { id } }",
                response_data={"user": {"id": "1", "__typename": "UserAccount"}},
            )
        ]
        schema = extract_graphql_schema(traces)
        assert "UserAccount" in schema.registry.types

    def test_fallback_to_capitalized_field_name(self):
        traces = [
            _gql_trace(
                "{ user { id } }",
                response_data={"user": {"id": "1"}},
            )
        ]
        schema = extract_graphql_schema(traces)
        assert "User" in schema.registry.types

    def test_capitalize_snake_case(self):
        assert _capitalize_field_name("order_items") == "OrderItems"

    def test_capitalize_camel_case(self):
        assert _capitalize_field_name("orderItems") == "OrderItems"


class TestTypeRegistryAccumulation:
    def test_same_type_from_multiple_traces(self):
        """Fields from different traces for the same type get merged."""
        traces = [
            _gql_trace(
                "query A { user { id name } }",
                response_data={"user": {"id": "1", "name": "Alice", "__typename": "User"}},
                trace_id="t_0001",
            ),
            _gql_trace(
                "query B { user { id email } }",
                response_data={"user": {"id": "2", "email": "b@b.com", "__typename": "User"}},
                trace_id="t_0002",
            ),
        ]
        schema = extract_graphql_schema(traces)
        user_type = schema.registry.types["User"]
        # All fields from both traces should be present
        assert {"id", "name", "email"} <= set(user_type.fields.keys())
        assert user_type.observation_count >= 2


class TestListInference:
    def test_list_of_objects(self):
        traces = [
            _gql_trace(
                "{ users { id name } }",
                response_data={
                    "users": [
                        {"id": "1", "name": "Alice", "__typename": "User"},
                        {"id": "2", "name": "Bob", "__typename": "User"},
                    ]
                },
            )
        ]
        schema = extract_graphql_schema(traces)
        query_type = schema.registry.types["Query"]
        users_field = query_type.fields["users"]
        assert users_field.is_list is True
        assert users_field.type_name == "User"

    def test_list_of_scalars(self):
        traces = [
            _gql_trace(
                "{ user { tags } }",
                response_data={"user": {"tags": ["admin", "active"], "__typename": "User"}},
            )
        ]
        schema = extract_graphql_schema(traces)
        user_type = schema.registry.types["User"]
        tags_field = user_type.fields["tags"]
        assert tags_field.is_list is True
        assert tags_field.type_name == "String"


class TestNullability:
    def test_null_value_marks_nullable(self):
        traces = [
            _gql_trace(
                "{ user { id email } }",
                response_data={"user": {"id": "1", "email": None, "__typename": "User"}},
            )
        ]
        schema = extract_graphql_schema(traces)
        user_type = schema.registry.types["User"]
        assert user_type.fields["email"].is_nullable is True


class TestEnumDetection:
    def test_enum_from_variable(self):
        traces = [
            _gql_trace(
                "query GetUsers($role: Role!) { users(role: $role) { id } }",
                response_data={"users": [{"id": "1"}]},
                variables={"role": "ADMIN"},
            )
        ]
        schema = extract_graphql_schema(traces)
        assert "Role" in schema.registry.enums
        assert "ADMIN" in schema.registry.enums["Role"].values

    def test_enum_values_accumulate(self):
        traces = [
            _gql_trace(
                "query Q($s: Status!) { items(s: $s) { id } }",
                response_data={"items": []},
                variables={"s": "ACTIVE"},
                trace_id="t_0001",
            ),
            _gql_trace(
                "query Q($s: Status!) { items(s: $s) { id } }",
                response_data={"items": []},
                variables={"s": "ARCHIVED"},
                trace_id="t_0002",
            ),
        ]
        schema = extract_graphql_schema(traces)
        assert schema.registry.enums["Status"].values == {"ACTIVE", "ARCHIVED"}

    def test_builtin_scalar_not_treated_as_enum(self):
        """String, Int, etc. variable types should not generate enums."""
        traces = [
            _gql_trace(
                "query Q($name: String!) { user(name: $name) { id } }",
                response_data={"user": {"id": "1"}},
                variables={"name": "Alice"},
            )
        ]
        schema = extract_graphql_schema(traces)
        assert "String" not in schema.registry.enums


class TestInputTypes:
    def test_input_type_from_variable(self):
        traces = [
            _gql_trace(
                "mutation M($input: CreateUserInput!) { createUser(input: $input) { id } }",
                response_data={"createUser": {"id": "1"}},
                variables={"input": {"name": "Alice", "age": 30}},
            )
        ]
        schema = extract_graphql_schema(traces)
        assert "CreateUserInput" in schema.registry.types
        input_type = schema.registry.types["CreateUserInput"]
        assert input_type.kind == "input"
        assert "name" in input_type.fields
        assert "age" in input_type.fields
        assert input_type.fields["name"].type_name == "String"
        assert input_type.fields["age"].type_name == "Int"


class TestStripTypeModifiers:
    @pytest.mark.parametrize(
        "input_str, expected",
        [
            ("ID!", "ID"),
            ("[String!]!", "String"),
            ("[String]", "String"),
            ("CreateUserInput", "CreateUserInput"),
            ("Int", "Int"),
        ],
    )
    def test_strip(self, input_str: str, expected: str) -> None:
        assert _strip_type_modifiers(input_str) == expected


class TestNestedObjects:
    def test_nested_type_extraction(self):
        traces = [
            _gql_trace(
                "{ user { id address { city country } } }",
                response_data={
                    "user": {
                        "id": "1",
                        "__typename": "User",
                        "address": {
                            "city": "Paris",
                            "country": "FR",
                            "__typename": "Address",
                        },
                    }
                },
            )
        ]
        schema = extract_graphql_schema(traces)
        assert "User" in schema.registry.types
        assert "Address" in schema.registry.types
        addr = schema.registry.types["Address"]
        assert "city" in addr.fields
        assert "country" in addr.fields


# ===========================================================================
# 3. SDL assembly tests
# ===========================================================================


class TestSDLAssembly:
    def _make_schema(self) -> GraphQLSchemaData:
        """Build a minimal schema for assembly tests."""
        registry = TypeRegistry()
        query = registry.get_or_create_type("Query")
        query.fields["user"] = FieldRecord(name="user", type_name="User")
        query.fields["users"] = FieldRecord(
            name="users", type_name="User", is_list=True
        )

        user = registry.get_or_create_type("User")
        user.description = "A user of the application"
        user.fields["id"] = FieldRecord(
            name="id", type_name="ID", is_nullable=False, is_always_present=True
        )
        user.fields["name"] = FieldRecord(
            name="name", type_name="String", is_nullable=False, is_always_present=True
        )
        user.fields["email"] = FieldRecord(
            name="email", type_name="String", is_nullable=True
        )

        return GraphQLSchemaData(
            registry=registry,
            root_query_fields=["user", "users"],
        )

    def test_basic_sdl(self):
        sdl = build_sdl(self._make_schema())
        assert "type Query" in sdl
        assert "type User" in sdl
        assert "id: ID!" in sdl
        assert "name: String!" in sdl
        assert "email: String" in sdl

    def test_list_field(self):
        sdl = build_sdl(self._make_schema())
        # users should be rendered as a list type
        assert "[User!" in sdl

    def test_type_description(self):
        sdl = build_sdl(self._make_schema())
        assert '"""A user of the application"""' in sdl


class TestSDLInputType:
    def test_input_type_rendered(self):
        registry = TypeRegistry()
        input_type = registry.get_or_create_type("CreateUserInput", kind="input")
        input_type.fields["name"] = FieldRecord(name="name", type_name="String")
        input_type.fields["age"] = FieldRecord(name="age", type_name="Int")

        schema = GraphQLSchemaData(registry=registry)
        sdl = build_sdl(schema)
        assert "input CreateUserInput" in sdl
        assert "name: String" in sdl
        assert "age: Int" in sdl


class TestSDLEnum:
    def test_enum_rendered(self):
        registry = TypeRegistry()
        registry.enums["Role"] = EnumRecord(
            name="Role", values={"ADMIN", "USER", "MODERATOR"}
        )

        schema = GraphQLSchemaData(registry=registry)
        sdl = build_sdl(schema)
        assert "enum Role" in sdl
        assert "ADMIN" in sdl
        assert "MODERATOR" in sdl
        assert "USER" in sdl

    def test_enum_with_description(self):
        registry = TypeRegistry()
        registry.enums["Status"] = EnumRecord(
            name="Status",
            values={"ACTIVE", "INACTIVE"},
            description="Account status",
        )
        schema = GraphQLSchemaData(registry=registry)
        sdl = build_sdl(schema)
        assert '"""Account status"""' in sdl


class TestSDLFieldArguments:
    def test_field_arguments(self):
        registry = TypeRegistry()
        query = registry.get_or_create_type("Query")
        query.fields["user"] = FieldRecord(
            name="user",
            type_name="User",
            arguments={"id": "ID!"},
        )
        user = registry.get_or_create_type("User")
        user.fields["id"] = FieldRecord(name="id", type_name="ID")

        schema = GraphQLSchemaData(
            registry=registry, root_query_fields=["user"]
        )
        sdl = build_sdl(schema)
        assert "user(id: ID!): User" in sdl


class TestSDLInterfaces:
    def test_implements_rendered(self):
        registry = TypeRegistry()
        user = registry.get_or_create_type("User")
        user.interfaces.add("Node")
        user.fields["id"] = FieldRecord(name="id", type_name="ID")

        schema = GraphQLSchemaData(registry=registry)
        sdl = build_sdl(schema)
        assert "type User implements Node" in sdl


class TestSDLFieldDescription:
    def test_field_description_rendered(self):
        registry = TypeRegistry()
        user = registry.get_or_create_type("User")
        user.fields["id"] = FieldRecord(
            name="id", type_name="ID", description="Unique identifier"
        )

        schema = GraphQLSchemaData(registry=registry)
        sdl = build_sdl(schema)
        assert '"""Unique identifier"""' in sdl


class TestSDLEmpty:
    def test_empty_schema(self):
        schema = GraphQLSchemaData()
        sdl = build_sdl(schema)
        assert sdl == ""


class TestSDLMutation:
    def test_mutation_root(self):
        registry = TypeRegistry()
        mutation = registry.get_or_create_type("Mutation")
        mutation.fields["createUser"] = FieldRecord(
            name="createUser", type_name="User"
        )
        user = registry.get_or_create_type("User")
        user.fields["id"] = FieldRecord(name="id", type_name="ID")

        schema = GraphQLSchemaData(
            registry=registry, root_mutation_fields=["createUser"]
        )
        sdl = build_sdl(schema)
        assert "type Mutation" in sdl
        assert "createUser: User" in sdl


# ===========================================================================
# 4. __typename injection tests
# ===========================================================================


class TestInjectTypename:
    def test_simple_query(self):
        result = inject_typename("{ user { name } }")
        assert "__typename" in result

    def test_already_has_typename_not_duplicated(self):
        """Should not double-inject __typename in a selection set that already has it."""
        # Both selection sets already have __typename
        query = "{ user { name __typename } __typename }"
        result = inject_typename(query)
        # Each selection set should still have exactly one __typename
        assert result.count("__typename") == 2

    def test_nested_selection_sets(self):
        result = inject_typename("{ user { name address { city } } }")
        # __typename should appear in both inner and outer selection sets
        assert result.count("__typename") >= 2

    def test_unparseable_query_returned_unchanged(self):
        bad_query = "this is not graphql"
        assert inject_typename(bad_query) == bad_query

    def test_mutation(self):
        result = inject_typename(
            "mutation { createUser(name: \"Bob\") { id } }"
        )
        assert "__typename" in result


# ===========================================================================
# 5. Integration: parse → extract → assemble
# ===========================================================================


class TestEndToEnd:
    def test_full_pipeline(self):
        """Parse traces, extract schema, assemble SDL — full round trip."""
        traces = [
            _gql_trace(
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
            _gql_trace(
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
