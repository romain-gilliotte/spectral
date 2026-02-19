"""Tests for cli/helpers/http.py."""

from cli.formats.capture_bundle import Header
from cli.helpers.http import get_header


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
