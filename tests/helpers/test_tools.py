"""Tests for LLM investigation tools and the tool_use conversation loop."""
# pyright: reportPrivateUsage=false

import base64
import json
from typing import Any

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest

import cli.helpers.llm as llm
from cli.helpers.llm._client import set_test_model
from cli.helpers.llm.tools._decode_base64 import execute as execute_decode_base64
from cli.helpers.llm.tools._decode_jwt import execute as execute_decode_jwt
from cli.helpers.llm.tools._decode_url import execute as execute_decode_url

# --- Executor unit tests (sync, no mocks) ---


class TestDecodeBase64:
    def test_simple_text(self):
        encoded = base64.b64encode(b"hello world").decode()
        assert execute_decode_base64(encoded) == "hello world"

    def test_json_payload(self):
        payload = json.dumps({"page": 1, "size": 20})
        encoded = base64.b64encode(payload.encode()).decode()
        result = execute_decode_base64(encoded)
        assert json.loads(result) == {"page": 1, "size": 20}

    def test_urlsafe_variant(self):
        data = b"\xfb\xff\xfe"
        encoded = base64.urlsafe_b64encode(data).decode()
        assert "-" in encoded or "_" in encoded
        result = execute_decode_base64(encoded)
        assert result.startswith("<binary:")

    def test_missing_padding(self):
        encoded = base64.b64encode(b"test").decode().rstrip("=")
        assert execute_decode_base64(encoded) == "test"

    def test_binary_returns_hex(self):
        data = bytes(range(256))
        encoded = base64.b64encode(data).decode()
        result = execute_decode_base64(encoded)
        assert result.startswith("<binary:")
        assert "00010203" in result

    def test_invalid_input(self):
        result = execute_decode_base64("!!!not-base64!!!")
        assert "Cannot base64-decode" in result


class TestDecodeUrl:
    def test_simple(self):
        assert execute_decode_url("hello%20world") == "hello world"

    def test_complex(self):
        assert execute_decode_url("%2Fapi%2Fdata%3Fq%3D1") == "/api/data?q=1"

    def test_already_decoded(self):
        assert execute_decode_url("already decoded") == "already decoded"


class TestDecodeJwt:
    def test_valid_jwt(self):
        header = (
            base64.urlsafe_b64encode(
                json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
            )
            .decode()
            .rstrip("=")
        )
        payload = (
            base64.urlsafe_b64encode(
                json.dumps({"sub": "1234", "name": "Test"}).encode()
            )
            .decode()
            .rstrip("=")
        )
        token = f"{header}.{payload}.fakesignature"

        result = execute_decode_jwt(token)
        decoded = json.loads(result)
        assert decoded["header"]["alg"] == "HS256"
        assert decoded["payload"]["sub"] == "1234"

    def test_invalid_jwt(self):
        result = execute_decode_jwt("not-a-jwt")
        assert "expected at least 2" in result

    def test_non_json_payload(self):
        """JWT-shaped token where a segment is valid base64 but not JSON."""
        header = (
            base64.urlsafe_b64encode(
                json.dumps({"alg": "HS256"}).encode()
            )
            .decode()
            .rstrip("=")
        )
        # Not valid JSON
        bad_payload = base64.urlsafe_b64encode(b"not-json-{foo").decode().rstrip("=")
        token = f"{header}.{bad_payload}.sig"

        result = execute_decode_jwt(token)
        decoded = json.loads(result)
        assert decoded["header"]["alg"] == "HS256"
        assert isinstance(decoded["payload"], str)


# --- Conversation tool-use tests (async, with FunctionModel) ---


class TestCallWithTools:
    @pytest.mark.asyncio
    async def test_direct_response_no_tool_use(self):
        """When the LLM responds without tool_use, return text directly."""
        call_count = {"n": 0}

        def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
            call_count["n"] += 1
            return ModelResponse(parts=[TextPart(content='{"endpoints": []}')])

        set_test_model(FunctionModel(model_fn))

        conv = llm.Conversation(
            tool_names=["decode_base64", "decode_url", "decode_jwt"],
        )
        result = await conv.ask_text("hi")
        assert result == '{"endpoints": []}'
        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_one_tool_round_then_response(self):
        """LLM calls decode_base64, gets result, then responds with text."""
        encoded = base64.b64encode(b'{"page":1}').decode()
        call_count = {"n": 0}

        def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ModelResponse(parts=[
                    ToolCallPart(
                        tool_name="decode_base64",
                        args={"value": encoded},
                        tool_call_id="tool_01",
                    ),
                ])
            return ModelResponse(parts=[TextPart(
                content='[{"method":"GET","pattern":"/api/data/{param}","urls":[]}]'
            )])

        set_test_model(FunctionModel(model_fn))

        conv = llm.Conversation(
            tool_names=["decode_base64", "decode_url", "decode_jwt"],
        )
        result = await conv.ask_text("analyze")
        assert "/api/data/{param}" in result
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_max_iterations_raises(self):
        """If the LLM keeps calling tools beyond max_iterations, raise."""

        def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="decode_url",
                    args={"value": "%20"},
                    tool_call_id="tool_loop",
                ),
            ])

        set_test_model(FunctionModel(model_fn))

        conv = llm.Conversation(
            tool_names=["decode_base64", "decode_url", "decode_jwt"],
            max_iterations=3,
        )
        with pytest.raises(Exception):
            await conv.ask_text("go")
