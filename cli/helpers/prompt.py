"""Load and render Jinja2 prompt templates from cli/prompts/."""

from __future__ import annotations

import importlib.resources

from jinja2 import Environment, StrictUndefined

_env = Environment(
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
)


def _read_template(name: str) -> str:
    """Read a .j2 file from the cli.prompts package."""
    ref = importlib.resources.files("cli.prompts").joinpath(name)
    return ref.read_text(encoding="utf-8")


def render(template: str, **variables: object) -> str:
    """Load *template* from cli/prompts/ and render it with *variables*."""
    source = _read_template(template)
    return _env.from_string(source).render(**variables)


def load(template: str) -> str:
    """Load *template* from cli/prompts/ and return it as-is (no variables)."""
    return _read_template(template)
