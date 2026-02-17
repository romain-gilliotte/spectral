"""Pipeline steps for the analysis engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from cli.analyze.steps.base import LLMStep as LLMStep
from cli.analyze.steps.base import MechanicalStep as MechanicalStep
from cli.analyze.steps.base import Step as Step
from cli.analyze.steps.base import StepValidationError as StepValidationError


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
