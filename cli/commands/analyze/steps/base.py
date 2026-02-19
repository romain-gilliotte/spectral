"""Base classes for analysis pipeline steps."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

In = TypeVar("In")
Out = TypeVar("Out")


class StepValidationError(Exception):
    """Raised when a step's output fails validation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details: dict[str, Any] = details or {}


class Step(ABC, Generic[In, Out]):
    """Base class for a typed pipeline step.

    Each step transforms an input of type In to an output of type Out.
    Subclasses must implement _execute and optionally _validate_output.
    """

    name: str = "step"

    @abstractmethod
    async def run(self, input: In) -> Out:
        """Execute the step and return the result."""
        ...

    def _validate_output(self, output: Out) -> None:
        """Validate the step output. Raises StepValidationError on failure.

        Override in subclasses to add validation logic. Default is no-op.
        """
        pass


class MechanicalStep(Step[In, Out]):
    """A step that uses only mechanical (non-LLM) processing.

    Mechanical steps fail fast on validation errors — no retry.
    """

    @abstractmethod
    async def _execute(self, input: In) -> Out:
        """Implement the mechanical transformation."""
        ...

    async def run(self, input: In) -> Out:
        output = await self._execute(input)
        self._validate_output(output)
        return output


class LLMStep(Step[In, Out]):
    """A step that uses LLM calls for semantic inference.

    LLM steps retry once on validation failure, asking the LLM to correct.
    """

    max_retries: int = 1

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    async def _execute(self, input: In) -> Out:
        """Implement the LLM-based transformation."""
        ...

    async def _retry(self, input: In, error: StepValidationError) -> Out:
        """Retry after a validation failure. Override for custom retry logic.

        Default behavior: re-execute without modification.
        """
        return await self._execute(input)

    async def run(self, input: In) -> Out:
        output = await self._execute(input)
        for attempt in range(self.max_retries + 1):
            try:
                self._validate_output(output)
                return output
            except StepValidationError as e:
                if attempt >= self.max_retries:
                    raise
                output = await self._retry(input, e)
        return output
