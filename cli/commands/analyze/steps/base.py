"""Base classes for analysis pipeline steps and protocol branches."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from cli.commands.analyze.steps.types import BranchContext, BranchOutput
from cli.commands.capture.types import Trace

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


class ProtocolBranch(ABC):
    """Abstract base for a protocol-specific analysis branch.

    Each protocol (REST, GraphQL, ...) implements this class.
    The pipeline orchestrates branches generically without knowing
    protocol-specific details.

    Set ``catch_all = True`` for a branch that receives all traces
    not claimed by any specific-protocol branch (e.g. unsupported
    protocol logging).
    """

    protocol: str
    file_extension: str
    label: str
    catch_all: bool = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for attr in ("protocol", "file_extension", "label"):
            if not hasattr(cls, attr):
                raise TypeError(
                    f"{cls.__name__} must define class attribute '{attr}'"
                )

    @abstractmethod
    async def run(
        self, traces: list[Trace], ctx: BranchContext
    ) -> BranchOutput | None:
        """Run the full branch pipeline and return an output, or None on failure."""
        ...
