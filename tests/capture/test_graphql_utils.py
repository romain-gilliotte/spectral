"""Tests for GraphQL __typename injection."""

from __future__ import annotations

from cli.commands.capture.graphql_utils import inject_typename


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
