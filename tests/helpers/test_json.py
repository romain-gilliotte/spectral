"""Tests for cli.helpers.json utilities (extraction, debug formatting)."""

from cli.helpers.json import extract_json, minified, reformat_json_lines


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


class TestExtractJson:
    def test_plain_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_json_in_markdown_block(self):
        text = 'Some text\n```json\n{"a": 1}\n```\nMore text'
        assert extract_json(text) == {"a": 1}

    def test_json_embedded_in_text(self):
        text = 'Here is the result: {"a": 1} hope that helps'
        assert extract_json(text) == {"a": 1}

    def test_array(self):
        assert extract_json("[1, 2, 3]") == [1, 2, 3]

    def test_raises_on_no_json(self):
        import pytest

        with pytest.raises(ValueError, match="Could not extract JSON"):
            extract_json("no json here")
