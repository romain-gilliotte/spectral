"""Tests for cli.helpers.json utilities."""

from cli.helpers.json import (
    compact,
    minified,
    reformat_json_lines,
    truncate_json,
)


class TestReformatJsonLines:
    def test_json_paragraphs_reformatted(self):
        blob = '{"key":"value","list":[1,2,3]}'
        text = f"Some preamble text.\n\n{blob}\n\nMore text after."
        result = reformat_json_lines(text)
        # The JSON paragraph should be reformatted (readable style)
        assert "Some preamble text." in result
        assert "More text after." in result
        # The reformatted JSON should still contain the data
        assert '"key"' in result
        assert '"value"' in result

    def test_non_json_paragraphs_untouched(self):
        text = "Hello world.\n\nThis is not JSON.\n\nNeither is this."
        result = reformat_json_lines(text)
        assert result == text


class TestMinified:
    def test_no_spaces_no_newlines(self):
        obj = {"key": "value", "list": [1, 2, 3]}
        result = minified(obj)
        assert " " not in result
        assert "\n" not in result
        assert result == '{"key":"value","list":[1,2,3]}'

    def test_unicode_preserved(self):
        obj = {"name": "caf\u00e9", "city": "\u6771\u4eac"}
        result = minified(obj)
        assert "caf\u00e9" in result
        assert "\u6771\u4eac" in result
        assert "\\u" not in result


class TestCompact:
    def test_collapses_short_blocks(self):
        obj = {"name": "Alice", "tags": ["admin", "user"], "address": {"city": "Paris", "zip": "75001"}}
        result = compact(obj)
        assert '["admin", "user"]' in result
        assert '{"city": "Paris", "zip": "75001"}' in result
        assert "\n" in result

    def test_expands_large_blocks(self):
        obj = {"data": ["a" * 30, "b" * 30, "c" * 30]}
        result = compact(obj)
        lines = result.strip().splitlines()
        assert len(lines) > 2


class TestTruncateJson:
    def test_truncates_dict_keys(self):
        obj = {f"key{i}": i for i in range(20)}
        result = truncate_json(obj, max_keys=5)
        assert len([k for k in result if k != "_truncated"]) == 5
        assert "_truncated" in result
        assert "15 more keys" in result["_truncated"]

    def test_truncates_list_items(self):
        obj = list(range(10))
        result = truncate_json(obj)
        assert len(result) == 4  # 3 items + "...7 more items"
        assert "7 more items" in result[-1]

    def test_truncates_long_strings(self):
        obj = {"text": "x" * 500}
        result = truncate_json(obj)
        assert len(result["text"]) == 203  # 200 + "..."
        assert result["text"].endswith("...")

    def test_respects_depth(self):
        obj = {"a": {"b": {"c": {"d": "deep"}}}}
        result = truncate_json(obj, max_depth=2)
        assert result["a"]["b"] == {"_truncated": "1 keys"}

    def test_passthrough_small_object(self):
        obj = {"a": 1, "b": "hello", "c": True}
        result = truncate_json(obj)
        assert result == obj

    def test_passthrough_scalars(self):
        assert truncate_json(42) == 42
        assert truncate_json("short") == "short"
        assert truncate_json(True) is True
        assert truncate_json(None) is None
