"""Tests for the Step base class."""

import pytest

from cli.commands.analyze.steps.base import (
    Step,
    StepValidationError,
)


class TestStep:
    @pytest.mark.asyncio
    async def test_simple_execution(self):
        class DoubleStep(Step[int, int]):
            name = "double"

            async def _execute(self, input: int) -> int:
                return input * 2

        step = DoubleStep()
        assert await step.run(5) == 10

    @pytest.mark.asyncio
    async def test_validation_failure_raises(self):
        class PositiveOnly(Step[int, int]):
            name = "positive"

            async def _execute(self, input: int) -> int:
                return input

            def _validate_output(self, output: int) -> None:
                if output < 0:
                    raise StepValidationError("Must be positive", {"value": output})

        step = PositiveOnly()
        assert await step.run(5) == 5

        with pytest.raises(StepValidationError, match="Must be positive"):
            await step.run(-1)

    @pytest.mark.asyncio
    async def test_no_retry_on_failure(self):
        """Step fails fast — no retry."""
        call_count = [0]

        class FailStep(Step[int, int]):
            name = "fail"

            async def _execute(self, input: int) -> int:
                call_count[0] += 1
                return -1

            def _validate_output(self, output: int) -> None:
                raise StepValidationError("always fails")

        step = FailStep()
        with pytest.raises(StepValidationError):
            await step.run(1)
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_string_step(self):
        class EchoStep(Step[str, str]):
            name = "echo"

            async def _execute(self, input: str) -> str:
                return f"echo: {input}"

        step = EchoStep()
        assert await step.run("hello") == "echo: hello"


class TestStepValidationError:
    def test_message_and_details(self):
        err = StepValidationError("something wrong", {"key": "val"})
        assert str(err) == "something wrong"
        assert err.details == {"key": "val"}

    def test_default_details(self):
        err = StepValidationError("oops")
        assert err.details == {}
