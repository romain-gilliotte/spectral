# pyright: reportPrivateUsage=false
"""Tests for refresh token extraction and refresh script validation."""

from __future__ import annotations

import json

import pytest

from cli.commands.capture.types import CaptureBundle, Trace
from cli.helpers.auth._errors import AuthScriptInvalid
from cli.helpers.auth._extract import extract_refresh_token
from cli.helpers.auth._generation import (
    extract_refresh_script,
    get_refresh_instructions,
)
from tests.conftest import make_trace

BASE_URL = "https://api.example.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_trace(
    trace_id: str, url: str, timestamp: int, response_body: bytes = b""
) -> Trace:
    return make_trace(
        trace_id,
        "POST",
        url,
        200,
        timestamp=timestamp,
        response_body=response_body,
    )


def _bundle_with_traces(traces: list[Trace]) -> CaptureBundle:
    from unittest.mock import MagicMock

    bundle = MagicMock(spec=CaptureBundle)
    bundle.traces = traces
    return bundle


# ---------------------------------------------------------------------------
# extract_refresh_token
# ---------------------------------------------------------------------------


class TestExtractRefreshToken:
    def test_finds_refresh_token_in_response(self) -> None:
        body = json.dumps(
            {"access_token": "at_123", "refresh_token": "rt_abc", "expires_in": 3600}
        ).encode()
        traces = [_post_trace("t1", f"{BASE_URL}/oauth/token", 100, body)]
        bundle = _bundle_with_traces(traces)

        result = extract_refresh_token(bundle, BASE_URL)

        assert result == "rt_abc"

    def test_finds_camel_case_refresh_token(self) -> None:
        body = json.dumps(
            {"accessToken": "at_123", "refreshToken": "rt_camel"}
        ).encode()
        traces = [_post_trace("t1", f"{BASE_URL}/auth/login", 100, body)]
        bundle = _bundle_with_traces(traces)

        result = extract_refresh_token(bundle, BASE_URL)

        assert result == "rt_camel"

    def test_picks_most_recent(self) -> None:
        old_body = json.dumps({"refresh_token": "rt_old"}).encode()
        new_body = json.dumps({"refresh_token": "rt_new"}).encode()
        traces = [
            _post_trace("t1", f"{BASE_URL}/login", 100, old_body),
            _post_trace("t2", f"{BASE_URL}/login", 300, new_body),
        ]
        bundle = _bundle_with_traces(traces)

        result = extract_refresh_token(bundle, BASE_URL)

        assert result == "rt_new"

    def test_ignores_get_traces(self) -> None:
        body = json.dumps({"refresh_token": "rt_get"}).encode()
        traces = [
            make_trace("t1", "GET", f"{BASE_URL}/data", 200, timestamp=100, response_body=body)
        ]
        bundle = _bundle_with_traces(traces)

        result = extract_refresh_token(bundle, BASE_URL)

        assert result is None

    def test_ignores_other_base_url(self) -> None:
        body = json.dumps({"refresh_token": "rt_other"}).encode()
        traces = [_post_trace("t1", "https://other.com/login", 100, body)]
        bundle = _bundle_with_traces(traces)

        result = extract_refresh_token(bundle, BASE_URL)

        assert result is None

    def test_no_json_body(self) -> None:
        traces = [_post_trace("t1", f"{BASE_URL}/login", 100, b"not json")]
        bundle = _bundle_with_traces(traces)

        result = extract_refresh_token(bundle, BASE_URL)

        assert result is None

    def test_empty_body(self) -> None:
        traces = [_post_trace("t1", f"{BASE_URL}/login", 100, b"")]
        bundle = _bundle_with_traces(traces)

        result = extract_refresh_token(bundle, BASE_URL)

        assert result is None

    def test_no_traces(self) -> None:
        bundle = _bundle_with_traces([])

        result = extract_refresh_token(bundle, BASE_URL)

        assert result is None

    def test_ignores_empty_refresh_token(self) -> None:
        body = json.dumps({"refresh_token": ""}).encode()
        traces = [_post_trace("t1", f"{BASE_URL}/login", 100, body)]
        bundle = _bundle_with_traces(traces)

        result = extract_refresh_token(bundle, BASE_URL)

        assert result is None


# ---------------------------------------------------------------------------
# extract_refresh_script
# ---------------------------------------------------------------------------

VALID_REFRESH_SCRIPT = """\
```python
def refresh_token(current_refresh_token):
    return {"headers": {"Authorization": "Bearer new"}}
```
"""

MISSING_REFRESH_FN = """\
```python
def acquire_token():
    return {"headers": {}}
```
"""

NO_AUTH_TEXT = "No refresh mechanism found. NO_AUTH"


class TestExtractRefreshScript:
    def test_valid_refresh_script(self) -> None:
        result = extract_refresh_script(VALID_REFRESH_SCRIPT)
        assert result is not None
        assert "def refresh_token" in result

    def test_missing_refresh_fn_raises(self) -> None:
        with pytest.raises(AuthScriptInvalid, match="must define a refresh_token"):
            extract_refresh_script(MISSING_REFRESH_FN)

    def test_no_auth_sentinel_returns_none(self) -> None:
        result = extract_refresh_script(NO_AUTH_TEXT)
        assert result is None


# ---------------------------------------------------------------------------
# get_refresh_instructions
# ---------------------------------------------------------------------------


class TestGetRefreshInstructions:
    def test_returns_non_empty_string(self) -> None:
        result = get_refresh_instructions()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "refresh_token" in result
