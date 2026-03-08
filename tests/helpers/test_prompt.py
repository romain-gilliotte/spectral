"""Tests for cli.helpers.prompt."""

from jinja2 import UndefinedError
import pytest

from cli.helpers.prompt import load, render


def test_render_basic():
    result = render("auth-instructions.j2", no_auth_sentinel="NO_AUTH")
    assert "NO_AUTH" in result
    assert "acquire_token" in result


def test_render_strict_undefined():
    with pytest.raises(UndefinedError):
        render("auth-instructions.j2")


def test_load_static():
    result = load("auth-extract-headers.j2")
    assert "authentication" in result
    assert "{{" not in result


def test_load_missing_template():
    with pytest.raises(FileNotFoundError):
        load("nonexistent-template.j2")


def test_render_with_list():
    result = render("detect-base-url.j2", lines=["  GET https://api.example.com/foo", "  POST https://api.example.com/bar"])
    assert "GET https://api.example.com/foo" in result
    assert "POST https://api.example.com/bar" in result


def test_render_conditional_sections():
    result_with = render(
        "mcp-identify-user.j2",
        existing_tools_text="## Tools\n- tool_a",
        target_trace_id="t_0001",
        request_details="GET /api/foo",
    )
    assert "## Tools" in result_with
    assert "t_0001" in result_with

    result_without = render(
        "mcp-identify-user.j2",
        existing_tools_text="",
        target_trace_id="t_0001",
        request_details="GET /api/foo",
    )
    assert "## Tools" not in result_without
    assert "t_0001" in result_without
