"""Base class for analysis pipeline steps."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Generic, TypeVar

In = TypeVar("In")
Out = TypeVar("Out")


class StepValidationError(Exception):
    """Raised when a step's output fails validation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details: dict[str, Any] = details or {}


class Step(Generic[In, Out]):
    """Base class for a typed pipeline step.

    Each step transforms an input of type In to an output of type Out.
    Subclasses must implement _execute and optionally _validate_output.
    """

    name: str = "step"

    @abstractmethod
    async def _execute(self, input: In) -> Out:
        """Implement the step transformation."""
        ...

    def _validate_output(self, output: Out) -> None:
        """Validate the step output. Raises StepValidationError on failure.

        Override in subclasses to add validation logic. Default is no-op.
        """
        pass

    async def run(self, input: In) -> Out:
        """Execute the step, validate output, and return the result."""
        output = await self._execute(input)
        self._validate_output(output)
        return output
