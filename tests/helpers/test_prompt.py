"""Tests for cli.helpers.prompt."""

from collections import Counter

from jinja2 import UndefinedError
import pytest

from cli.formats.mcp_tool import ToolDefinition, ToolRequest
from cli.helpers.prompt import load, render
from tests.conftest import make_trace


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


def test_render_with_counter():
    counts: Counter[tuple[str, str]] = Counter()
    counts[("GET", "https://api.example.com/foo")] = 1
    counts[("POST", "https://api.example.com/bar")] = 2
    result = render("detect-base-urls.j2", counts=counts)
    assert "GET https://api.example.com/foo" in result
    assert "POST https://api.example.com/bar" in result


def test_render_conditional_sections():
    existing = [
        ToolDefinition(
            name="tool_a",
            description="A tool",
            parameters={"type": "object", "properties": {}},
            request=ToolRequest(method="GET", url="https://api.example.com/api/a"),
        ),
    ]
    target = make_trace("t_0001", "GET", "https://api.example.com/foo", 200, 1000)

    result_with = render(
        "mcp-identify-user.j2",
        existing_tools=existing,
        target=target,
        request_body=None,
    )
    assert "tool_a" in result_with
    assert "do NOT duplicate" in result_with
    assert "t_0001" in result_with

    result_without = render(
        "mcp-identify-user.j2",
        existing_tools=[],
        target=target,
        request_body=None,
    )
    assert "tool_a" not in result_without
    assert "t_0001" in result_without
