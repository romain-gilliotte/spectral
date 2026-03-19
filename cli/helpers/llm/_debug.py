"""Debug logging helpers for LLM conversations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from cli.helpers.console import console
from cli.helpers.json import reformat_json_lines

_debug_dir: Path | None = None


def _format_args(args: str | dict[str, Any] | None) -> str:
    """Normalize tool call args to a JSON string."""
    if args is None:
        return "{}"
    if isinstance(args, dict):
        return json.dumps(args, ensure_ascii=False)
    return args


def _summarize_args(args: str | dict[str, Any] | None) -> str:
    """Build a short args summary for result headers, e.g. ``(t_0001)``."""
    if args is None:
        return ""
    d = json.loads(args) if isinstance(args, str) else args
    if not d:
        return ""
    vals = [str(v) for v in d.values()]
    return "(" + ", ".join(vals) + ")"


def init_debug(*, debug: bool = False, debug_dir: Path | None = None) -> None:
    """Configure debug logging. Auto-creates a timestamped dir when debug=True."""
    global _debug_dir
    if debug and debug_dir is None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        debug_dir = Path("debug") / ts
        debug_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"  Debug logs → {debug_dir}")
    _debug_dir = debug_dir


def clear_debug_dir() -> None:
    """Reset the debug directory (for tests)."""
    global _debug_dir
    _debug_dir = None


class DebugSession:
    """Accumulates debug turns for a single LLM call, appending to a file on each add."""

    def __init__(self, call_name: str):
        self._call_args: dict[str, str] = {}
        if _debug_dir is None:
            self._path: Path | None = None
        else:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            self._path = _debug_dir / f"{ts}_{call_name}"

    def record_tools(self, tools: dict[str, str]) -> None:
        """Write a tools summary header at the top of the debug file."""
        if self._path is None or not tools:
            return
        lines = [f"  - {name}: {desc}" for name, desc in tools.items()]
        self._append("=== TOOLS ===\n" + "\n".join(lines) + "\n\n")

    def record_messages(self, messages: list[Any], prev_len: int) -> None:
        """Record new messages from a PydanticAI run."""
        if self._path is None:
            return

        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            SystemPromptPart,
            TextPart,
            ToolCallPart,
            ToolReturnPart,
            UserPromptPart,
        )

        new = messages[prev_len:]

        for msg in new:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, SystemPromptPart):
                        self._append(f"=== SYSTEM ===\n{part.content}\n")
                    elif isinstance(part, UserPromptPart):
                        text = reformat_json_lines(str(part.content))
                        self._append(f"=== PROMPT ===\n{text}\n")
                    elif isinstance(part, ToolReturnPart):
                        summary = self._call_args.pop(part.tool_call_id, "")
                        result = reformat_json_lines(str(part.content))
                        self._append(
                            f"=== RESULT: {part.tool_name}{summary} ===\n"
                            f"{result}\n"
                        )

            elif isinstance(msg, ModelResponse):
                tool_calls = [p for p in msg.parts if isinstance(p, ToolCallPart)]
                if tool_calls:
                    pending: list[str] = []
                    for part in msg.parts:
                        if isinstance(part, TextPart) and part.content.strip():
                            pending.append(f"=== ASSISTANT TEXT ===\n{part.content}")
                        elif isinstance(part, ToolCallPart):
                            args_str = _format_args(part.args)
                            if part.tool_name == "final_result":
                                pending.append(
                                    f"=== RESPONSE ===\n{reformat_json_lines(args_str)}"
                                )
                            else:
                                self._call_args[part.tool_call_id] = _summarize_args(
                                    part.args
                                )
                                pending.append(
                                    f"=== TOOL: {part.tool_name} ===\n"
                                    f"{reformat_json_lines(args_str)}"
                                )
                    if pending:
                        self._append("\n\n".join(pending) + "\n")
                else:
                    texts = [
                        p.content for p in msg.parts if isinstance(p, TextPart)
                    ]
                    if texts:
                        text = reformat_json_lines("\n".join(texts))
                        self._append(f"=== RESPONSE ===\n{text}\n")

    def _append(self, text: str) -> None:
        assert self._path is not None
        with self._path.open("a") as f:
            f.write(text)
