"""Core conversation engine built on PydanticAI Agent."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from cli.commands.capture.types import CaptureBundle
from cli.helpers.llm._client import ensure_api_key, get_test_model
from cli.helpers.llm._cost import record_usage
from cli.helpers.llm._debug import DebugSession
from cli.helpers.llm.tools import ToolDeps, make_tools

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

_model_override: str | None = None

T = TypeVar("T", bound=BaseModel)


def set_model(model: str) -> None:
    """Override the default model for all new conversations."""
    global _model_override
    _model_override = model


class Conversation:
    """A multi-turn conversation with the LLM.

    Config (system, tools, etc.) is fixed at construction.
    ``ask_text`` and ``ask_json`` are the two public methods.
    """

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
        self._system = self._join_system(system)
        self._model = _model_override or model
        self._max_tokens = max_tokens
        self._max_iterations = max_iterations
        self._label = label
        self._dbg = DebugSession(label or "call")

        if tool_names is not None:
            self._tools = make_tools(tool_names)
        else:
            self._tools = None

        self._deps = ToolDeps(
            traces=bundle.traces if bundle is not None else [],
            contexts=bundle.contexts if bundle is not None else [],
        )

        # PydanticAI message history for multi-turn
        self._messages: list[Any] = []

        # Ensure API key is available (skipped when a test model is injected)
        if get_test_model() is None:
            ensure_api_key()

    async def ask_text(self, prompt: str) -> str:
        """Send a user message and return the assistant's text response."""
        return await self._run(prompt, output_type=str)

    async def ask_json(self, prompt: str, response_model: type[T]) -> T:
        """Send a user message and return validated structured output.

        PydanticAI handles validation and retry via tool-calling.
        """
        return await self._run(prompt, output_type=response_model)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _run(self, prompt: str, *, output_type: Any) -> Any:
        """Run the agent and record results."""
        from pydantic_ai import Agent
        from pydantic_ai.models.anthropic import AnthropicModelSettings
        from pydantic_ai.usage import UsageLimits

        model: Any = get_test_model() or f"anthropic:{self._model}"

        settings = AnthropicModelSettings(
            max_tokens=self._max_tokens,
            anthropic_cache_instructions="5m",
            anthropic_cache_tool_definitions="5m",
            anthropic_cache_messages="5m",
        )

        agent = Agent(
            model,
            system_prompt=self._system or "",
            tools=self._tools or [],
            deps_type=ToolDeps,
            output_type=output_type,
            model_settings=settings,
        )

        result = await agent.run(
            prompt,
            deps=self._deps,
            message_history=self._messages,
            usage_limits=UsageLimits(request_limit=self._max_iterations),
        )

        self._dbg.record_messages(result.all_messages(), len(self._messages))
        self._messages = result.all_messages()
        record_usage(result.usage(), self._label, self._model)

        return result.output

    @staticmethod
    def _join_system(system: str | list[str] | None) -> str | None:
        """Collapse system prompts into a single string."""
        if system is None:
            return None
        if isinstance(system, str):
            return system
        return "\n\n".join(system)
