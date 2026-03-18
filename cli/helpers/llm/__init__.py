"""Centralized LLM client with a ``Conversation`` class.

Usage::

    import cli.helpers.llm as llm

    llm.init_debug(debug=True)

    conv = llm.Conversation(system="...", label="my_task")
    text = conv.ask_text(prompt)

For tests, import setup helpers directly from submodules::

    from cli.helpers.llm.providers.testing import set_test_model, clear_test_model
"""

from __future__ import annotations

from cli.helpers.llm._client import create_config_interactive, current_model
from cli.helpers.llm._conversation import Conversation
from cli.helpers.llm._cost import print_usage_summary
from cli.helpers.llm._debug import init_debug

__all__ = [
    "Conversation",
    "create_config_interactive",
    "current_model",
    "init_debug",
    "print_usage_summary",
]
