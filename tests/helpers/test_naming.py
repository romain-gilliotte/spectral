"""Tests for cli/helpers/naming.py."""

from cli.helpers.naming import python_type, safe_name, to_class_name, to_identifier


class TestSafeName:
    def test_basic(self) -> None:
        assert safe_name("user_id") == "user_id"

    def test_special_chars(self) -> None:
        assert safe_name("content-type") == "content_type"

    def test_digit_prefix(self) -> None:
        assert safe_name("3items") == "_3items"

    def test_keyword_escape(self) -> None:
        assert safe_name("class") == "class_"
        assert safe_name("type") == "type_"
        assert safe_name("import") == "import_"
        assert safe_name("from") == "from_"
        assert safe_name("return") == "return_"
        assert safe_name("for") == "for_"
        assert safe_name("in") == "in_"
        assert safe_name("is") == "is_"


class TestToIdentifier:
    def test_basic(self) -> None:
        assert to_identifier("get_users") == "get_users"

    def test_cleanup(self) -> None:
        assert to_identifier("get--users!!") == "get_users"

    def test_empty_uses_fallback(self) -> None:
        assert to_identifier("", fallback="request") == "request"
        assert to_identifier("---") == "unknown"

    def test_underscore_collapsing(self) -> None:
        assert to_identifier("a___b") == "a_b"

    def test_strips_leading_trailing(self) -> None:
        assert to_identifier("__hello__") == "hello"


class TestToClassName:
    def test_basic(self) -> None:
        assert to_class_name("my cool api") == "MyCoolApi"

    def test_suffix_appended(self) -> None:
        assert to_class_name("Acme Portal", suffix="Client") == "AcmePortalClient"

    def test_suffix_already_present(self) -> None:
        assert to_class_name("Acme Client", suffix="Client") == "AcmeClient"

    def test_empty_with_suffix(self) -> None:
        assert to_class_name("", suffix="Client") == "ApiClient"

    def test_empty_without_suffix(self) -> None:
        assert to_class_name("") == "Api"


class TestPythonType:
    def test_all_mappings(self) -> None:
        assert python_type("string") == "str"
        assert python_type("integer") == "int"
        assert python_type("number") == "float"
        assert python_type("boolean") == "bool"
        assert python_type("array") == "list"
        assert python_type("object") == "dict"

    def test_unknown_default(self) -> None:
        assert python_type("foobar") == "Any"

    def test_unknown_custom_fallback(self) -> None:
        assert python_type("foobar", fallback="str") == "str"
