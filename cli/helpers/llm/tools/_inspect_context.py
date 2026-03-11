"""LLM tool: inspect a UI context event."""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext

from cli.commands.capture.types import Context
from cli.helpers.json import minified, truncate_json
from cli.helpers.llm.tools._deps import ToolDeps


def execute(context_id: str, index: dict[str, Context]) -> str:
    """Core logic, importable for direct testing."""
    ctx = index.get(context_id)
    if ctx is None:
        return f"Context {context_id} not found"

    result: dict[str, Any] = {
        "action": ctx.meta.action,
        "element": {
            "tag": ctx.meta.element.tag,
            "text": ctx.meta.element.text,
            "selector": ctx.meta.element.selector,
            "attributes": ctx.meta.element.attributes,
        },
        "page": {
            "url": ctx.meta.page.url,
            "title": ctx.meta.page.title,
        },
    }
    if ctx.meta.page.content is not None:
        content = ctx.meta.page.content
        result["page_content"] = truncate_json(
            {
                "headings": content.headings,
                "navigation": content.navigation,
                "main_text": content.main_text,
                "forms": content.forms,
                "tables": content.tables,
                "alerts": content.alerts,
            },
            max_keys=20,
        )
    return minified(result)


def inspect_context(ctx: RunContext[ToolDeps], context_id: str) -> str:
    """Get full details for a UI context event.

    Returns action, element (tag, text, selector, attributes), page (url, title),
    and rich page content (headings, navigation, main text, forms, tables, alerts).

    Args:
        context_id: The context ID (e.g., 'c_0001').
    """
    return execute(context_id, ctx.deps.context_index)
