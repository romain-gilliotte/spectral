"""Tests for GraphQL type extraction from traces."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import pytest

from cli.commands.analyze.steps.graphql.extraction import (
    _capitalize_field_name,
    _infer_literal_type,
    _infer_scalar,
    _is_enum_literal,
    _resolve_from_variable,
    _strip_type_modifiers,
    extract_graphql_schema,
)
from tests.analyze.steps.graphql.conftest import gql_trace


class TestExtractSimple:
    def test_query_fields_tracked(self):
        traces = [
            gql_trace(
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
            gql_trace(
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
            gql_trace(
                "{ user { id } }",
                response_data={"user": {"id": "1", "__typename": "UserAccount"}},
            )
        ]
        schema = extract_graphql_schema(traces)
        assert "UserAccount" in schema.registry.types

    def test_fallback_to_capitalized_field_name(self):
        traces = [
            gql_trace(
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
            gql_trace(
                "query A { user { id name } }",
                response_data={"user": {"id": "1", "name": "Alice", "__typename": "User"}},
                trace_id="t_0001",
            ),
            gql_trace(
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
            gql_trace(
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
            gql_trace(
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
            gql_trace(
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
            gql_trace(
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
            gql_trace(
                "query Q($s: Status!) { items(s: $s) { id } }",
                response_data={"items": []},
                variables={"s": "ACTIVE"},
                trace_id="t_0001",
            ),
            gql_trace(
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
            gql_trace(
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
            gql_trace(
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
            gql_trace(
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


class TestAliasHandling:
    def test_aliases_resolve_to_real_field_names(self):
        """Aliases in queries should read values from aliased response keys
        but store fields under their real (non-aliased) schema names."""
        traces = [
            gql_trace(
                'query { myUser: user(id: "1") { userName: name userEmail: email } }',
                response_data={
                    "myUser": {
                        "__typename": "User",
                        "userName": "Alice",
                        "userEmail": "alice@example.com",
                    }
                },
            )
        ]
        schema = extract_graphql_schema(traces)

        # Root query field should be the real name, not the alias
        assert "user" in schema.root_query_fields
        assert "myUser" not in schema.root_query_fields

        # Type should exist and have fields under real names
        assert "User" in schema.registry.types
        user_type = schema.registry.types["User"]
        assert "name" in user_type.fields
        assert "email" in user_type.fields
        assert "userName" not in user_type.fields
        assert "userEmail" not in user_type.fields

        # Values should have been read correctly via alias keys
        assert user_type.fields["name"].type_name == "String"
        assert user_type.fields["email"].type_name == "String"


class TestResolveFromVariable:
    def test_known_variable(self):
        assert _resolve_from_variable("$id", {"id": "ID!"}) == "ID"

    def test_known_variable_no_bang(self):
        assert _resolve_from_variable("$limit", {"limit": "Int"}) == "Int"

    def test_known_variable_list_type(self):
        assert _resolve_from_variable("$ids", {"ids": "[ID!]!"}) == "[ID]"

    def test_unknown_variable(self):
        assert _resolve_from_variable("$unknown", {"id": "ID!"}) is None

    def test_non_variable(self):
        assert _resolve_from_variable('"hello"', {"hello": "String"}) is None

    def test_integer_literal(self):
        assert _resolve_from_variable("42", {"x": "Int"}) is None


class TestInferLiteralType:
    def test_quoted_string(self):
        assert _infer_literal_type('"hello"') == "String"

    def test_integer(self):
        assert _infer_literal_type("42") == "Int"

    def test_negative_integer(self):
        assert _infer_literal_type("-7") == "Int"

    def test_float(self):
        assert _infer_literal_type("3.14") == "Float"

    def test_negative_float(self):
        assert _infer_literal_type("-1.5") == "Float"

    def test_true(self):
        assert _infer_literal_type("true") == "Boolean"

    def test_false(self):
        assert _infer_literal_type("false") == "Boolean"

    def test_null(self):
        assert _infer_literal_type("null") == "JSON"

    def test_empty_list(self):
        assert _infer_literal_type("[]") == "[JSON]"

    def test_object(self):
        assert _infer_literal_type("{foo: 1}") == "JSON"

    def test_enum_like(self):
        # _infer_literal_type still returns "String" for bare identifiers;
        # enum detection now happens upstream in _walk_fields via _is_enum_literal
        assert _infer_literal_type("ACTIVE") == "String"


class TestIsEnumLiteral:
    def test_bare_identifier(self):
        assert _is_enum_literal("ACTIVE") is True

    def test_multi_word_identifier(self):
        assert _is_enum_literal("IN_PROGRESS") is True

    def test_quoted_string(self):
        assert _is_enum_literal('"hello"') is False

    def test_boolean_true(self):
        assert _is_enum_literal("true") is False

    def test_boolean_false(self):
        assert _is_enum_literal("false") is False

    def test_null(self):
        assert _is_enum_literal("null") is False

    def test_integer(self):
        assert _is_enum_literal("42") is False

    def test_float(self):
        assert _is_enum_literal("3.14") is False

    def test_variable_ref(self):
        assert _is_enum_literal("$status") is False

    def test_list(self):
        assert _is_enum_literal("[1, 2]") is False

    def test_object(self):
        assert _is_enum_literal("{foo: 1}") is False

    def test_empty(self):
        assert _is_enum_literal("") is False


class TestLiteralEnumDetection:
    def test_enum_from_literal_argument(self):
        """query { items(status: ACTIVE) { id } } → inferred enum created."""
        traces = [
            gql_trace(
                "query { items(status: ACTIVE) { id } }",
                response_data={"items": [{"id": "1"}]},
            )
        ]
        schema = extract_graphql_schema(traces)
        enum_name = "InferredQueryItemsStatusEnum"
        assert enum_name in schema.registry.enums
        assert "ACTIVE" in schema.registry.enums[enum_name].values
        # Argument type should reference the inferred enum
        query_type = schema.registry.types["Query"]
        assert query_type.fields["items"].arguments["status"] == enum_name

    def test_literal_enum_values_accumulate(self):
        """Two traces with different literal enum values → both in the same enum."""
        traces = [
            gql_trace(
                "query { items(status: ACTIVE) { id } }",
                response_data={"items": [{"id": "1"}]},
                trace_id="t_0001",
            ),
            gql_trace(
                "query { items(status: ARCHIVED) { id } }",
                response_data={"items": [{"id": "2"}]},
                trace_id="t_0002",
            ),
        ]
        schema = extract_graphql_schema(traces)
        enum_name = "InferredQueryItemsStatusEnum"
        assert schema.registry.enums[enum_name].values == {"ACTIVE", "ARCHIVED"}

    def test_literal_enum_rendered_in_sdl(self):
        """End-to-end: literal enum produces valid enum definition in SDL."""
        from cli.commands.analyze.steps.graphql.assemble import build_sdl

        traces = [
            gql_trace(
                "query { items(status: ACTIVE) { id } }",
                response_data={"items": [{"id": "1"}]},
            )
        ]
        schema = extract_graphql_schema(traces)
        sdl = build_sdl(schema)
        assert "enum InferredQueryItemsStatusEnum" in sdl
        assert "ACTIVE" in sdl

    def test_variable_type_takes_precedence_over_literal_enum(self):
        """Variable-resolved type overwrites a previously inferred enum type."""
        traces = [
            gql_trace(
                "query { items(status: ACTIVE) { id } }",
                response_data={"items": [{"id": "1"}]},
                trace_id="t_0001",
            ),
            gql_trace(
                "query Q($s: Status!) { items(status: $s) { id } }",
                response_data={"items": [{"id": "2"}]},
                variables={"s": "ACTIVE"},
                trace_id="t_0002",
            ),
        ]
        schema = extract_graphql_schema(traces)
        query_type = schema.registry.types["Query"]
        # Variable-resolved type should win
        assert query_type.fields["items"].arguments["status"] == "Status"

    def test_literal_enum_not_created_for_boolean(self):
        """Boolean literal arguments should not create inferred enums."""
        traces = [
            gql_trace(
                "query { items(active: true) { id } }",
                response_data={"items": [{"id": "1"}]},
            )
        ]
        schema = extract_graphql_schema(traces)
        query_type = schema.registry.types["Query"]
        assert query_type.fields["items"].arguments["active"] == "Boolean"
        # No inferred enum should exist
        assert not any("Active" in name for name in schema.registry.enums)

    def test_literal_enum_not_created_for_string(self):
        """Quoted string arguments should not create inferred enums."""
        traces = [
            gql_trace(
                'query { user(name: "Alice") { id } }',
                response_data={"user": {"id": "1", "__typename": "User"}},
            )
        ]
        schema = extract_graphql_schema(traces)
        assert len(schema.registry.enums) == 0

    def test_literal_enum_on_mutation(self):
        """Literal enum detection works on Mutation root type too."""
        traces = [
            gql_trace(
                "mutation { updateStatus(status: PUBLISHED) { id } }",
                response_data={"updateStatus": {"id": "1"}},
            )
        ]
        schema = extract_graphql_schema(traces)
        enum_name = "InferredMutationUpdateStatusStatusEnum"
        assert enum_name in schema.registry.enums
        assert "PUBLISHED" in schema.registry.enums[enum_name].values


class TestArgumentResolutionIntegration:
    def test_variable_ref_resolves_to_type(self):
        """query($id: ID!) { user(id: $id) } → arguments == {"id": "ID"}"""
        traces = [
            gql_trace(
                "query GetUser($id: ID!) { user(id: $id) { name } }",
                response_data={"user": {"name": "Alice", "__typename": "User"}},
                variables={"id": "123"},
            )
        ]
        schema = extract_graphql_schema(traces)
        query_type = schema.registry.types["Query"]
        assert query_type.fields["user"].arguments == {"id": "ID"}

    def test_literal_int_resolves_to_int(self):
        """{ user(id: 1) } → arguments == {"id": "Int"}"""
        traces = [
            gql_trace(
                "{ user(id: 1) { name } }",
                response_data={"user": {"name": "Alice", "__typename": "User"}},
            )
        ]
        schema = extract_graphql_schema(traces)
        query_type = schema.registry.types["Query"]
        assert query_type.fields["user"].arguments == {"id": "Int"}

    def test_literal_string_resolves_to_string(self):
        traces = [
            gql_trace(
                '{ user(name: "Alice") { id } }',
                response_data={"user": {"id": "1", "__typename": "User"}},
            )
        ]
        schema = extract_graphql_schema(traces)
        query_type = schema.registry.types["Query"]
        assert query_type.fields["user"].arguments == {"name": "String"}

    def test_variable_ref_overwrites_literal(self):
        """If a literal was seen first, a variable ref in a later trace should overwrite."""
        traces = [
            gql_trace(
                "{ user(id: 1) { name } }",
                response_data={"user": {"name": "Alice", "__typename": "User"}},
                trace_id="t_0001",
            ),
            gql_trace(
                "query GetUser($id: ID!) { user(id: $id) { name } }",
                response_data={"user": {"name": "Bob", "__typename": "User"}},
                variables={"id": "123"},
                trace_id="t_0002",
            ),
        ]
        schema = extract_graphql_schema(traces)
        query_type = schema.registry.types["Query"]
        # Variable-resolved type should win over literal
        assert query_type.fields["user"].arguments == {"id": "ID"}

    def test_variable_ref_preserved_over_literal(self):
        """If a variable ref was seen first, a literal in a later trace should not overwrite."""
        traces = [
            gql_trace(
                "query GetUser($id: ID!) { user(id: $id) { name } }",
                response_data={"user": {"name": "Alice", "__typename": "User"}},
                variables={"id": "123"},
                trace_id="t_0001",
            ),
            gql_trace(
                "{ user(id: 1) { name } }",
                response_data={"user": {"name": "Bob", "__typename": "User"}},
                trace_id="t_0002",
            ),
        ]
        schema = extract_graphql_schema(traces)
        query_type = schema.registry.types["Query"]
        # Variable-resolved type from first trace should be preserved
        assert query_type.fields["user"].arguments == {"id": "ID"}

    def test_list_variable_preserved_over_empty_list(self):
        """Variable ref giving [Int] should not be overwritten by a [] literal."""
        traces = [
            gql_trace(
                "query Q($ids: [Int!]!) { users(ids: $ids) { name } }",
                response_data={"users": [{"name": "Alice", "__typename": "User"}]},
                variables={"ids": [1, 2]},
                trace_id="t_0001",
            ),
            gql_trace(
                "{ users(ids: []) { name } }",
                response_data={"users": []},
                trace_id="t_0002",
            ),
        ]
        schema = extract_graphql_schema(traces)
        query_type = schema.registry.types["Query"]
        # [Int] from variable should be preserved, not overwritten by [JSON]
        assert query_type.fields["users"].arguments == {"ids": "[Int]"}
