"""Tests for GraphQL SDL assembly."""

from __future__ import annotations

from cli.commands.analyze.steps.graphql.assemble import build_sdl
from cli.commands.analyze.steps.graphql.types import (
    EnumRecord,
    FieldRecord,
    GraphQLSchemaData,
    TypeRegistry,
)


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
