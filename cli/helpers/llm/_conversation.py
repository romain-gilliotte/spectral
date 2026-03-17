"""Core conversation engine built on PydanticAI Agent."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from cli.commands.capture.types import CaptureBundle
from cli.helpers.llm._client import get_or_create_config
from cli.helpers.llm._cost import record_usage
from cli.helpers.llm._debug import DebugSession
from cli.helpers.llm.tools import ToolDeps, make_tools

T = TypeVar("T", bound=BaseModel)


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
        max_tokens: int = 4096,
        max_iterations: int = 10,
        label: str = "",
    ) -> None:
        self._system = self._join_system(system)
        self._max_tokens = max_tokens
        self._max_iterations = max_iterations
        self._label = label
        self._dbg = DebugSession(label or "call")

        self._config = get_or_create_config()

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
        from pydantic_ai.agent import CallToolsNode
        from pydantic_ai.usage import UsageLimits

        from cli.helpers.llm.providers import build_model

        model, settings = build_model(
            self._config.provider,
            model_name=self._config.model,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            max_tokens=self._max_tokens,
        )

        agent_kwargs: dict[str, Any] = dict(
            model=model,
            tools=self._tools or [],
            deps_type=ToolDeps,
            output_type=output_type,
            model_settings=settings,
        )
        if self._system:
            agent_kwargs["system_prompt"] = self._system

        agent = Agent(**agent_kwargs)

        flushed_len = len(self._messages)

        async with agent.iter(
            prompt,
            deps=self._deps,
            message_history=self._messages,
            usage_limits=UsageLimits(request_limit=self._max_iterations),
        ) as agent_run:
            async for node in agent_run:
                if isinstance(node, CallToolsNode):
                    messages = agent_run.all_messages()
                    self._dbg.record_messages(messages, flushed_len)
                    flushed_len = len(messages)

        result = agent_run.result
        assert result is not None
        self._dbg.record_messages(result.all_messages(), flushed_len)
        self._messages = result.all_messages()
        record_usage(result.usage(), self._label)

        return result.output

    @staticmethod
    def _join_system(system: str | list[str] | None) -> str | None:
        """Collapse system prompts into a single string."""
        if system is None:
            return None
        if isinstance(system, str):
            return system
        return "\n\n".join(system)
