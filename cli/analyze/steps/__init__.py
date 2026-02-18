"""Pipeline steps for the analysis engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from cli.analyze.steps.base import (
    LLMStep as LLMStep,
    MechanicalStep as MechanicalStep,
    Step as Step,
    StepValidationError as StepValidationError,
)


@dataclass
class EndpointGroup:
    """An LLM-identified endpoint group."""

    method: str
    pattern: str
    urls: list[str] = field(default_factory=lambda: [])


__all__ = [
    "EndpointGroup",
    "LLMStep",
    "MechanicalStep",
    "Step",
    "StepValidationError",
]
