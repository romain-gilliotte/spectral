"""Tests for cli.helpers.auth.generation."""

from __future__ import annotations

import pytest

from cli.helpers.auth._errors import AuthScriptInvalid
from cli.helpers.auth._generation import extract_script, get_auth_instructions

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SCRIPT = """\
def acquire_token():
    return {"headers": {"Authorization": "Bearer tok"}}
"""

VALID_SCRIPT_FENCED = """\
Here is the auth script:

```python
def acquire_token():
    return {"headers": {"Authorization": "Bearer tok"}}
```
"""

NO_AUTH_TEXT = "The application does not require authentication. NO_AUTH"

NO_AUTH_WITH_FENCES = """\
NO_AUTH but here is a helper anyway:

```python
def acquire_token():
    return {"headers": {}}
```
"""

SYNTAX_ERROR_SCRIPT = """\
```python
def acquire_token(
    return {}
```
"""

IMPORT_ERROR_SCRIPT = """\
```python
import nonexistent_module_xyz_12345

def acquire_token():
    return {}
```
"""

MISSING_ACQUIRE_SCRIPT = """\
```python
def login():
    return {"headers": {"Authorization": "Bearer tok"}}
```
"""

ACQUIRE_NOT_CALLABLE = """\
```python
acquire_token = "not a function"
```
"""


# ---------------------------------------------------------------------------
# TestExtractScript
# ---------------------------------------------------------------------------


class TestExtractScript:
    def test_valid_script_in_markdown_fences(self) -> None:
        result = extract_script(VALID_SCRIPT_FENCED)
        assert result is not None
        assert "def acquire_token" in result
        assert result.endswith("\n")
        # Verify the extracted script does not contain fence markers
        assert "```" not in result

    def test_valid_script_without_fences(self) -> None:
        result = extract_script(VALID_SCRIPT)
        assert result is not None
        assert "def acquire_token" in result
        assert result.endswith("\n")

    def test_no_auth_sentinel_returns_none(self) -> None:
        result = extract_script(NO_AUTH_TEXT)
        assert result is None

    def test_no_auth_sentinel_with_fences_extracts_script(self) -> None:
        result = extract_script(NO_AUTH_WITH_FENCES)
        assert result is not None
        assert "def acquire_token" in result

    def test_syntax_error_raises(self) -> None:
        with pytest.raises(AuthScriptInvalid, match="syntax error"):
            extract_script(SYNTAX_ERROR_SCRIPT)

    def test_import_error_raises(self) -> None:
        with pytest.raises(AuthScriptInvalid, match="fails at import time"):
            extract_script(IMPORT_ERROR_SCRIPT)

    def test_missing_acquire_token_raises(self) -> None:
        with pytest.raises(AuthScriptInvalid, match="must define an acquire_token"):
            extract_script(MISSING_ACQUIRE_SCRIPT)

    def test_acquire_token_not_callable_raises(self) -> None:
        with pytest.raises(AuthScriptInvalid, match="must define an acquire_token"):
            extract_script(ACQUIRE_NOT_CALLABLE)


# ---------------------------------------------------------------------------
# TestGetAuthInstructions
# ---------------------------------------------------------------------------


class TestGetAuthInstructions:
    def test_returns_non_empty_string(self) -> None:
        result = get_auth_instructions()
        assert isinstance(result, str)
        assert len(result) > 0
