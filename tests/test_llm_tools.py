"""Tests for LLM investigation tools and the tool_use conversation loop."""

import base64
import json
from unittest.mock import MagicMock

import pytest

from cli.analyze.tools import (
    _call_with_tools,
    _execute_decode_base64,
    _execute_decode_jwt,
    _execute_decode_url,
    _TOOL_EXECUTORS,
    INVESTIGATION_TOOLS,
)
from cli.analyze.steps.detect_base_url import DetectBaseUrlStep


# --- Executor unit tests (sync, no mocks) ---


class TestDecodeBase64:
    def test_simple_text(self):
        encoded = base64.b64encode(b"hello world").decode()
        assert _execute_decode_base64(encoded) == "hello world"

    def test_json_payload(self):
        payload = json.dumps({"page": 1, "size": 20})
        encoded = base64.b64encode(payload.encode()).decode()
        result = _execute_decode_base64(encoded)
        assert json.loads(result) == {"page": 1, "size": 20}

    def test_urlsafe_variant(self):
        # URL-safe base64 uses - and _ instead of + and /
        data = b"\xfb\xff\xfe"  # produces +//+ in standard, uses -_ in urlsafe
        encoded = base64.urlsafe_b64encode(data).decode()
        assert "-" in encoded or "_" in encoded  # sanity
        result = _execute_decode_base64(encoded)
        assert result.startswith("<binary:")

    def test_missing_padding(self):
        encoded = base64.b64encode(b"test").decode().rstrip("=")
        assert _execute_decode_base64(encoded) == "test"

    def test_binary_returns_hex(self):
        data = bytes(range(256))
        encoded = base64.b64encode(data).decode()
        result = _execute_decode_base64(encoded)
        assert result.startswith("<binary:")
        assert "00010203" in result

    def test_invalid_input(self):
        with pytest.raises(ValueError, match="Cannot base64-decode"):
            _execute_decode_base64("!!!not-base64!!!")


class TestDecodeUrl:
    def test_simple(self):
        assert _execute_decode_url("hello%20world") == "hello world"

    def test_complex(self):
        assert _execute_decode_url("%2Fapi%2Fdata%3Fq%3D1") == "/api/data?q=1"

    def test_already_decoded(self):
        assert _execute_decode_url("already decoded") == "already decoded"


class TestDecodeJwt:
    def test_valid_jwt(self):
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "1234", "name": "Test"}).encode()).decode().rstrip("=")
        token = f"{header}.{payload}.fakesignature"

        result = _execute_decode_jwt(token)
        decoded = json.loads(result)
        assert decoded["header"]["alg"] == "HS256"
        assert decoded["payload"]["sub"] == "1234"

    def test_invalid_jwt(self):
        with pytest.raises(ValueError, match="expected at least 2"):
            _execute_decode_jwt("not-a-jwt")


# --- _call_with_tools tests (async, mocked client) ---


def _make_text_response(text: str):
    """Create a mock response with a single text block and end_turn stop."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    return resp


def _make_tool_use_response(tool_name: str, tool_input: dict, tool_use_id: str = "tool_01"):
    """Create a mock response with a tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_use_id
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [block]
    return resp


class TestCallWithTools:
    @pytest.mark.asyncio
    async def test_direct_response_no_tool_use(self):
        """When the LLM responds without tool_use, return text directly."""
        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            return _make_text_response('{"endpoints": []}')

        client = MagicMock()
        client.messages.create = mock_create

        result = await _call_with_tools(
            client, "model", [{"role": "user", "content": "hi"}],
            INVESTIGATION_TOOLS, _TOOL_EXECUTORS,
        )
        assert result == '{"endpoints": []}'
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_one_tool_round_then_response(self):
        """LLM calls decode_base64, gets result, then responds with text."""
        encoded = base64.b64encode(b'{"page":1}').decode()
        tool_resp = _make_tool_use_response("decode_base64", {"value": encoded})
        final_resp = _make_text_response('[{"method":"GET","pattern":"/api/data/{param}","urls":[]}]')

        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_resp
            return final_resp

        client = MagicMock()
        client.messages.create = mock_create

        result = await _call_with_tools(
            client, "model", [{"role": "user", "content": "analyze"}],
            INVESTIGATION_TOOLS, _TOOL_EXECUTORS,
        )
        assert "/api/data/{param}" in result
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_executor_error_returned_as_is_error(self):
        """When an executor raises, the error is sent back with is_error=True."""
        tool_resp = _make_tool_use_response("decode_base64", {"value": "!!!not~base64$$$"})
        final_resp = _make_text_response("[]")

        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_resp
            # Verify the tool_result has is_error
            messages = kwargs["messages"]
            last_user_msg = messages[-1]
            tool_results = last_user_msg["content"]
            assert any(tr.get("is_error") for tr in tool_results)
            return final_resp

        client = MagicMock()
        client.messages.create = mock_create

        result = await _call_with_tools(
            client, "model", [{"role": "user", "content": "go"}],
            INVESTIGATION_TOOLS, _TOOL_EXECUTORS,
        )
        assert result == "[]"

    @pytest.mark.asyncio
    async def test_max_iterations_raises(self):
        """If the LLM keeps calling tools beyond max_iterations, raise ValueError."""
        tool_resp = _make_tool_use_response("decode_url", {"value": "%20"})

        async def mock_create(**kwargs):
            return tool_resp

        client = MagicMock()
        client.messages.create = mock_create

        with pytest.raises(ValueError, match="exceeded 3 iterations"):
            await _call_with_tools(
                client, "model", [{"role": "user", "content": "go"}],
                INVESTIGATION_TOOLS, _TOOL_EXECUTORS,
                max_iterations=3,
            )

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        """If the LLM calls a tool not in executors, return an error result."""
        tool_resp = _make_tool_use_response("nonexistent_tool", {"x": 1})
        final_resp = _make_text_response("done")

        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_resp
            messages = kwargs["messages"]
            tool_results = messages[-1]["content"]
            assert any("Unknown tool" in tr.get("content", "") for tr in tool_results)
            assert any(tr.get("is_error") for tr in tool_results)
            return final_resp

        client = MagicMock()
        client.messages.create = mock_create

        result = await _call_with_tools(
            client, "model", [{"role": "user", "content": "go"}],
            INVESTIGATION_TOOLS, _TOOL_EXECUTORS,
        )
        assert result == "done"


class TestDetectBaseUrlStep:
    @pytest.mark.asyncio
    async def test_returns_base_url(self):
        """DetectBaseUrlStep should parse the LLM response and return the base_url string."""
        async def mock_create(**kwargs):
            return _make_text_response('{"base_url": "https://www.example.com/api"}')

        client = MagicMock()
        client.messages.create = mock_create

        step = DetectBaseUrlStep(client, "model")
        result = await step.run(
            [("GET", "https://www.example.com/api/users"), ("GET", "https://cdn.example.com/style.css")],
        )
        assert result == "https://www.example.com/api"

    @pytest.mark.asyncio
    async def test_strips_trailing_slash(self):
        """Trailing slash should be stripped from the returned base URL."""
        async def mock_create(**kwargs):
            return _make_text_response('{"base_url": "https://api.example.com/"}')

        client = MagicMock()
        client.messages.create = mock_create

        step = DetectBaseUrlStep(client, "model")
        result = await step.run([("GET", "https://api.example.com/v1")])
        assert result == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_origin_only(self):
        """LLM may return just the origin without a path prefix."""
        async def mock_create(**kwargs):
            return _make_text_response('{"base_url": "https://api.example.com"}')

        client = MagicMock()
        client.messages.create = mock_create

        step = DetectBaseUrlStep(client, "model")
        result = await step.run([("GET", "https://api.example.com/users")])
        assert result == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_invalid_response_raises(self):
        """If the LLM doesn't return {base_url: ...}, raise ValueError."""
        async def mock_create(**kwargs):
            return _make_text_response('{"something_else": "value"}')

        client = MagicMock()
        client.messages.create = mock_create

        step = DetectBaseUrlStep(client, "model")
        with pytest.raises(ValueError, match="Expected"):
            await step.run([("GET", "https://example.com/api")])
