"""Tests for cli/helpers/ modules (naming, subprocess, http)."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from cli.formats.capture_bundle import Header
from cli.helpers.http import get_header
from cli.helpers.naming import python_type, safe_name, to_class_name, to_identifier
from cli.helpers.subprocess import run_cmd


# ── naming ────────────────────────────────────────────────────────


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
        assert to_class_name("EDF Portal", suffix="Client") == "EdfPortalClient"

    def test_suffix_already_present(self) -> None:
        assert to_class_name("EDF Client", suffix="Client") == "EdfClient"

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


# ── subprocess ────────────────────────────────────────────────────


class TestRunCmd:
    def test_success(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["echo"], returncode=0, stdout="hello\n", stderr=""
            )
            result = run_cmd(["echo", "hello"], "Echo test")
            assert result.stdout == "hello\n"

    def test_failure_raises_runtime_error(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["false"], returncode=1, stdout="", stderr="boom"
            )
            with pytest.raises(RuntimeError, match="Doing stuff \\(exit 1\\): boom"):
                run_cmd(["false"], "Doing stuff")

    def test_error_message_format(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=42, stdout="", stderr="bad thing"
            )
            with pytest.raises(RuntimeError, match=r"\(exit 42\)"):
                run_cmd(["x"], "Build")

    def test_timeout_forwarded(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            run_cmd(["sleep", "0"], "Sleep test", timeout=999)
            _, kwargs = mock_run.call_args
            assert kwargs["timeout"] == 999


# ── http ──────────────────────────────────────────────────────────


class TestGetHeader:
    def test_found(self) -> None:
        headers = [Header(name="Content-Type", value="application/json")]
        assert get_header(headers, "Content-Type") == "application/json"

    def test_not_found(self) -> None:
        headers = [Header(name="Content-Type", value="application/json")]
        assert get_header(headers, "Authorization") is None

    def test_case_insensitive(self) -> None:
        headers = [Header(name="content-type", value="text/html")]
        assert get_header(headers, "Content-Type") == "text/html"

    def test_first_match_wins(self) -> None:
        headers = [
            Header(name="X-Custom", value="first"),
            Header(name="X-Custom", value="second"),
        ]
        assert get_header(headers, "X-Custom") == "first"
