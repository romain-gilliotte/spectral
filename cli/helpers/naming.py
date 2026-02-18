"""Python codegen naming utilities shared across generators."""

from __future__ import annotations

import re

_PYTHON_KEYWORDS = frozenset({
    "class", "type", "import", "from", "return", "def",
    "if", "for", "in", "is",
})

_JSON_TO_PYTHON = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


def safe_name(name: str) -> str:
    """Sanitize a string to a valid Python identifier, escaping keywords."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if name and name[0].isdigit():
        name = "_" + name
    if name in _PYTHON_KEYWORDS:
        name = name + "_"
    return name


def to_identifier(name: str, *, fallback: str = "unknown") -> str:
    """Clean a name into a valid Python identifier (snake_case).

    Strips non-alphanumeric chars, collapses underscores, strips leading/trailing.
    Returns *fallback* if the result is empty.
    """
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or fallback


def to_class_name(name: str, *, suffix: str = "") -> str:
    """Convert a free-form name to PascalCase.

    If *suffix* is given and the result doesn't already end with it,
    appends it.  Returns ``"Api" + suffix`` as a last resort.
    """
    words = re.split(r"[^a-zA-Z0-9]+", name)
    class_name = "".join(w.capitalize() for w in words if w)
    if not class_name:
        return f"Api{suffix}" if suffix else "Api"
    if suffix and not class_name.endswith(suffix):
        class_name += suffix
    return class_name


def python_type(json_type: str, *, fallback: str = "Any") -> str:
    """Map a JSON type string to a Python type hint."""
    return _JSON_TO_PYTHON.get(json_type, fallback)
