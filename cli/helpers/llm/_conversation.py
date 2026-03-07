"""Core conversation engine: Conversation class, tool loop, response model parsing."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from typing import Any, TypeVar, cast, overload

from pydantic import BaseModel, ValidationError

from cli.commands.capture.types import CaptureBundle
from cli.helpers.json import extract_json
from cli.helpers.llm._client import send
from cli.helpers.llm._debug import DebugSession
from cli.helpers.llm._utils import extract_text
from cli.helpers.llm.tools import execute_tool, make_tools

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

_model_override: str | None = None

T = TypeVar("T", bound=BaseModel)


def set_model(model: str) -> None:
    """Override the default model for all new conversations."""
    global _model_override
    _model_override = model


class Conversation:
    """A multi-turn conversation with the LLM.

    Config (system, tools, executors, etc.) is fixed at construction.
    ``ask_text(prompt)`` and ``ask_json(prompt, response_model)`` are the
    two public methods.
    """

    _CACHE_EPHEMERAL: dict[str, str] = {"type": "ephemeral"}

    def __init__(
        self,
        *,
        system: str | list[str] | None = None,
        tool_names: Sequence[str] | None = None,
        bundle: CaptureBundle | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
        max_iterations: int = 10,
        label: str = "",
    ) -> None:
        self._system_blocks = self._build_system_blocks(system)
        self._model = _model_override or model
        self._max_tokens = max_tokens
        self._max_iterations = max_iterations
        self._label = label
        self._messages: list[dict[str, Any]] = []
        self._dbg = DebugSession(label or "call")

        if tool_names is not None:
            tools, executors = make_tools(tool_names, bundle)
            if tools:
                tools[-1] = {**tools[-1], "cache_control": self._CACHE_EPHEMERAL}
            self._tools: list[dict[str, Any]] | None = tools
            self._executors: dict[str, Callable[[dict[str, Any]], str]] | None = executors
        else:
            self._tools = None
            self._executors = None

    async def ask_text(self, prompt: str) -> str:
        """Send a user message and return the assistant's text response."""
        self._messages.append({"role": "user", "content": prompt})
        self._dbg.add_user(prompt)

        if self._tools is not None and self._executors is not None:
            text = await self._run_tool_loop()
        else:
            create_kwargs: dict[str, Any] = {}
            if self._system_blocks:
                create_kwargs["system"] = self._system_blocks

            response: Any = await send(
                label=self._label,
                model=self._model,
                max_tokens=self._max_tokens,
                messages=self._messages,
                **create_kwargs,
            )
            text = extract_text(response.content)
            self._dbg.add_assistant(text)
            self._check_truncation(response)

        self._messages.append({"role": "assistant", "content": text})
        return text

    @overload
    async def ask_json(self, prompt: str, response_model: type[T]) -> T: ...
    @overload
    async def ask_json(self, prompt: str, response_model: None = None) -> Any: ...

    async def ask_json(self, prompt: str, response_model: type[T] | None = None) -> T | Any:
        """Send a user message, parse the response as JSON, and return a validated model.

        If *response_model* is ``None``, returns the raw parsed JSON (dict/list)
        without Pydantic validation.  Otherwise augments *prompt* with a JSON
        instruction and retries once on parse/validation failure.
        """
        augmented = (
            prompt
            + "\n\nIMPORTANT: Respond with a single minified JSON value. "
            "No commentary, no markdown fences, no explanation — only raw JSON."
        )
        text = await self.ask_text(augmented)

        if response_model is None:
            return self._parse_raw_json(text)

        try:
            return self._try_parse_model(text, response_model)
        except (json.JSONDecodeError, ValidationError, ValueError) as first_err:
            parse_error = first_err

        retry_msg = (
            f"Your response could not be parsed: {parse_error}. "
            f"Please respond with valid JSON matching the expected schema: "
            f"{json.dumps(response_model.model_json_schema())}"
        )
        retry_text = await self.ask_text(retry_msg)
        return self._try_parse_model(retry_text, response_model)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_system_blocks(
        system: str | list[str] | None,
    ) -> list[dict[str, Any]] | None:
        """Convert *system* into a list of text blocks with ``cache_control``."""
        if system is None:
            return None
        eph: dict[str, str] = {"type": "ephemeral"}
        if isinstance(system, str):
            return [{"type": "text", "text": system, "cache_control": eph}]
        if len(system) == 1:
            return [{"type": "text", "text": system[0], "cache_control": eph}]
        return [
            {"type": "text", "text": system[0], "cache_control": eph},
            {"type": "text", "text": "\n\n".join(system[1:]), "cache_control": eph},
        ]

    def _check_truncation(self, response: Any) -> None:
        """Raise if the response was truncated due to max_tokens."""
        if getattr(response, "stop_reason", None) == "max_tokens":
            tag = f" ({self._label})" if self._label else ""
            raise ValueError(
                f"LLM response truncated{tag} (max_tokens={self._max_tokens}). "
                f"The prompt or expected output is too large."
            )

    @staticmethod
    def _parse_raw_json(text: str) -> Any:
        """Parse *text* as JSON without model validation."""
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            return extract_json(text)

    @staticmethod
    def _try_parse_model(text: str, response_model: type[T]) -> T:
        """Try to parse *text* as JSON and validate against *response_model*."""
        try:
            data = json.loads(text.strip())
        except json.JSONDecodeError:
            data = extract_json(text)
        return response_model.model_validate(data)

    async def _run_tool_loop(self) -> str:
        """Call the LLM with tool_use support, looping until a text response."""
        assert self._executors is not None

        if self._messages and isinstance(self._messages[0].get("content"), str):
            self._messages[0] = {
                **self._messages[0],
                "content": [
                    {
                        "type": "text",
                        "text": self._messages[0]["content"],
                        "cache_control": self._CACHE_EPHEMERAL,
                    }
                ],
            }

        create_kwargs: dict[str, Any] = {}
        if self._system_blocks:
            create_kwargs["system"] = self._system_blocks

        for _ in range(self._max_iterations):
            response: Any = await send(
                label=self._label,
                model=self._model,
                max_tokens=self._max_tokens,
                tools=self._tools,
                messages=self._messages,
                **create_kwargs,
            )

            if response.stop_reason == "max_tokens":
                self._dbg.add_assistant(extract_text(response.content) + "\n[TRUNCATED]")
                raise ValueError(
                    f"LLM response truncated ({self._label}, max_tokens={self._max_tokens}). "
                    f"The prompt or expected output is too large."
                )

            if response.stop_reason != "tool_use":
                text = extract_text(response.content)
                self._dbg.add_assistant(text)
                return text

            self._messages.append({"role": "assistant", "content": response.content})
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) == "text" and block.text.strip():
                    self._dbg.add_tool_text(block.text)
                if getattr(block, "type", None) != "tool_use":
                    continue
                tool_result, result_str, is_error = execute_tool(block, self._executors)
                tool_results.append(tool_result)
                self._dbg.add_tool_use(
                    name=block.name, input=block.input, result=result_str, error=is_error,
                )

            for msg in self._messages:
                if msg.get("role") != "user":
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for blk in cast(list[dict[str, Any]], content):
                    blk.pop("cache_control", None)

            if tool_results:
                tool_results[-1] = {**tool_results[-1], "cache_control": self._CACHE_EPHEMERAL}

            self._messages.append({"role": "user", "content": tool_results})

            self._dbg.flush_tool_round()

        raise ValueError(f"_run_tool_loop exceeded {self._max_iterations} iterations")
