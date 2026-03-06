"""JSON truncation helpers for LLM consumption."""

from __future__ import annotations

from typing import Any


def truncate_json(obj: Any, max_keys: int = 10, max_depth: int = 4) -> Any:
    """Truncate a JSON-like object for LLM consumption.

    Limits breadth (max_keys per dict, 3 items per list), depth, and string length.
    """
    return _truncate(obj, max_keys, max_depth, 0)


def _truncate(obj: Any, max_keys: int, max_depth: int, depth: int) -> Any:
    if depth >= max_depth:
        if isinstance(obj, dict):
            n: int = len(obj)  # pyright: ignore[reportUnknownArgumentType]
            return {"_truncated": f"{n} keys"}
        if isinstance(obj, list):
            n = len(obj)  # pyright: ignore[reportUnknownArgumentType]
            return [f"...{n} items"]
        if isinstance(obj, str) and len(obj) > 200:
            return obj[:200] + "..."
        return obj
    if isinstance(obj, dict):
        all_items: list[tuple[str, Any]] = list(obj.items())  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        items = all_items[:max_keys]
        result = {k: _truncate(v, max_keys, max_depth, depth + 1) for k, v in items}
        if len(all_items) > max_keys:
            result["_truncated"] = f"{len(all_items) - max_keys} more keys"
        return result
    if isinstance(obj, list):
        items_list: list[Any] = obj[:3]  # pyright: ignore[reportUnknownVariableType]
        truncated = [_truncate(item, max_keys, max_depth, depth + 1) for item in items_list]
        total: int = len(obj)  # pyright: ignore[reportUnknownArgumentType]
        if total > 3:
            truncated.append(f"...{total - 3} more items")
        return truncated
    if isinstance(obj, str) and len(obj) > 200:
        return obj[:200] + "..."
    return obj
