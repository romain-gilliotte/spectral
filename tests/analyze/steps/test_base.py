"""Tests for the Step base classes."""

import pytest

from cli.commands.analyze.steps.base import (
    LLMStep,
    MechanicalStep,
    StepValidationError,
)


class TestMechanicalStep:
    @pytest.mark.asyncio
    async def test_simple_execution(self):
        class DoubleStep(MechanicalStep[int, int]):
            name = "double"

            async def _execute(self, input: int) -> int:
                return input * 2

        step = DoubleStep()
        assert await step.run(5) == 10

    @pytest.mark.asyncio
    async def test_validation_failure_raises(self):
        class PositiveOnly(MechanicalStep[int, int]):
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
        """Mechanical steps fail fast — no retry."""
        call_count = [0]

        class FailStep(MechanicalStep[int, int]):
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


class TestLLMStep:
    @pytest.mark.asyncio
    async def test_simple_execution(self):
        class EchoStep(LLMStep[str, str]):
            name = "echo"

            async def _execute(self, input: str) -> str:
                return f"echo: {input}"

        step = EchoStep(model="test")
        assert await step.run("hello") == "echo: hello"

    @pytest.mark.asyncio
    async def test_retry_on_validation_failure(self):
        call_count = [0]

        class RetryableStep(LLMStep[str, str]):
            name = "retryable"

            async def _execute(self, input: str) -> str:
                call_count[0] += 1
                if call_count[0] == 1:
                    return "bad"
                return "good"

            def _validate_output(self, output: str) -> None:
                if output == "bad":
                    raise StepValidationError("output is bad")

            async def _retry(self, input: str, error: StepValidationError) -> str:
                return await self._execute(input)

        step = RetryableStep(model="test")
        result = await step.run("input")
        assert result == "good"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self):
        class AlwaysFailStep(LLMStep[str, str]):
            name = "always_fail"
            max_retries = 1

            async def _execute(self, input: str) -> str:
                return "bad"

            def _validate_output(self, output: str) -> None:
                raise StepValidationError("always bad")

        step = AlwaysFailStep(model="test")
        with pytest.raises(StepValidationError, match="always bad"):
            await step.run("input")


class TestStepValidationError:
    def test_message_and_details(self):
        err = StepValidationError("something wrong", {"key": "val"})
        assert str(err) == "something wrong"
        assert err.details == {"key": "val"}

    def test_default_details(self):
        err = StepValidationError("oops")
        assert err.details == {}
