"""Tests for the centralized LLM helper (cli/helpers/llm.py)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import cli.helpers.llm as llm


@pytest.fixture(autouse=True)
def reset_llm_globals():
    """Reset module globals before/after each test."""
    llm.reset()
    yield
    llm.reset()


def _make_mock_client(response: Any = None) -> MagicMock:
    """Build a mock client whose messages.create returns *response*."""
    client = MagicMock()
    mock_response = response or MagicMock()
    client.messages.create = AsyncMock(return_value=mock_response)
    return client


def _make_rate_limit_error(retry_after: str | None = None) -> Exception:
    """Build a fake anthropic.RateLimitError with optional retry-after header."""
    import anthropic

    resp = MagicMock()
    if retry_after is not None:
        resp.headers = {"retry-after": retry_after}
    else:
        resp.headers = {}
    resp.status_code = 429
    resp.json.return_value = {"error": {"message": "rate limited", "type": "rate_limit_error"}}
    return anthropic.RateLimitError(
        message="rate limited",
        response=resp,
        body={"error": {"message": "rate limited", "type": "rate_limit_error"}},
    )


class TestInit:
    def test_init_with_mock_client(self):
        mock = MagicMock()
        llm.init(client=mock)
        assert llm._client is mock  # pyright: ignore[reportPrivateUsage]
        assert llm._semaphore is not None  # pyright: ignore[reportPrivateUsage]

    def test_init_custom_concurrency(self):
        llm.init(client=MagicMock(), max_concurrent=3)
        sem = llm._semaphore  # pyright: ignore[reportPrivateUsage]
        assert sem is not None
        assert sem._value == 3  # pyright: ignore[reportPrivateUsage]


class TestCreate:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """Successful call on first attempt, no retry needed."""
        expected = MagicMock()
        client = _make_mock_client(expected)
        llm.init(client=client)

        result = await llm.create(model="m", max_tokens=10, messages=[])
        assert result is expected
        client.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limit_with_retry_after_header(self):
        """Rate limit -> retry-after header respected -> success on 2nd attempt."""
        expected = MagicMock()
        error = _make_rate_limit_error(retry_after="0.01")

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[error, expected])
        llm.init(client=client)

        result = await llm.create(model="m", max_tokens=10, messages=[])
        assert result is expected
        assert client.messages.create.await_count == 2

    @pytest.mark.asyncio
    async def test_rate_limit_fallback_exponential(self):
        """Rate limit without retry-after -> fallback exponential backoff."""
        expected = MagicMock()
        error = _make_rate_limit_error(retry_after=None)

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[error, expected])
        # Use a tiny backoff so the test runs fast.
        original_backoff = llm.FALLBACK_BACKOFF
        llm.FALLBACK_BACKOFF = 0.01
        try:
            llm.init(client=client)
            result = await llm.create(model="m", max_tokens=10, messages=[])
            assert result is expected
        finally:
            llm.FALLBACK_BACKOFF = original_backoff

    @pytest.mark.asyncio
    async def test_retries_exhausted_reraises(self):
        """All retries exhausted -> original RateLimitError is re-raised."""
        import anthropic

        error = _make_rate_limit_error(retry_after="0.01")

        client = MagicMock()
        client.messages.create = AsyncMock(
            side_effect=[error] * (llm.MAX_RETRIES + 1)
        )
        llm.init(client=client)

        with pytest.raises(anthropic.RateLimitError):
            await llm.create(model="m", max_tokens=10, messages=[])
        assert client.messages.create.await_count == llm.MAX_RETRIES + 1

    @pytest.mark.asyncio
    async def test_non_rate_limit_error_no_retry(self):
        """Non-rate-limit errors propagate immediately without retry."""
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=ValueError("boom"))
        llm.init(client=client)

        with pytest.raises(ValueError, match="boom"):
            await llm.create(model="m", max_tokens=10, messages=[])
        client.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """Semaphore prevents more than max_concurrent calls at once."""
        max_concurrent = 2
        concurrent_count = 0
        peak_concurrent = 0

        async def slow_create(**kwargs: Any) -> MagicMock:
            nonlocal concurrent_count, peak_concurrent
            concurrent_count += 1
            peak_concurrent = max(peak_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            return MagicMock()

        client = MagicMock()
        client.messages.create = slow_create
        llm.init(client=client, max_concurrent=max_concurrent)

        await asyncio.gather(*[
            llm.create(model="m", max_tokens=10, messages=[])
            for _ in range(6)
        ])
        assert peak_concurrent <= max_concurrent

    @pytest.mark.asyncio
    async def test_not_initialized_raises(self):
        """Calling create() before init() raises RuntimeError."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await llm.create(model="m", max_tokens=10, messages=[])
