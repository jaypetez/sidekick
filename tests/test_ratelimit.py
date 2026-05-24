"""Tests for the in-process token bucket rate limiter."""

from __future__ import annotations

import asyncio

import pytest

from sidekick import ratelimit
from sidekick.ratelimit import (
    RateLimiter,
    build_limiter_from_env,
    get_default_limiter,
    reset_default_limiter,
)


@pytest.mark.asyncio
async def test_acquire_within_budget_succeeds():
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        assert await limiter.acquire("user-a") is True


@pytest.mark.asyncio
async def test_acquire_over_budget_denies():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    assert await limiter.acquire("user-a") is True
    assert await limiter.acquire("user-a") is True
    assert await limiter.acquire("user-a") is False


@pytest.mark.asyncio
async def test_buckets_are_per_key():
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    assert await limiter.acquire("user-a") is True
    assert await limiter.acquire("user-a") is False
    # Different key gets its own bucket.
    assert await limiter.acquire("user-b") is True


@pytest.mark.asyncio
async def test_bucket_refills_over_time(monkeypatch):
    """Drain the bucket, advance the monotonic clock, then expect a refill."""
    fake_now = [1_000.0]

    def fake_monotonic():
        return fake_now[0]

    monkeypatch.setattr("sidekick.ratelimit.time.monotonic", fake_monotonic)
    limiter = RateLimiter(max_requests=2, window_seconds=10)

    assert await limiter.acquire("k") is True
    assert await limiter.acquire("k") is True
    assert await limiter.acquire("k") is False

    # Advance enough time for one token to refill (10s/2 tokens = 5s per token).
    fake_now[0] += 5.0
    assert await limiter.acquire("k") is True
    assert await limiter.acquire("k") is False


@pytest.mark.asyncio
async def test_concurrent_acquire_is_safe():
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    results = await asyncio.gather(*(limiter.acquire("k") for _ in range(20)))
    granted = sum(1 for r in results if r)
    # Exactly the bucket size should have been granted — never more.
    assert granted == 5


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        RateLimiter(max_requests=0, window_seconds=1)
    with pytest.raises(ValueError):
        RateLimiter(max_requests=1, window_seconds=0)


def test_build_limiter_from_env_uses_overrides(monkeypatch):
    monkeypatch.setenv("SIDEKICK_RATE_LIMIT_MAX", "7")
    monkeypatch.setenv("SIDEKICK_RATE_LIMIT_WINDOW_SECONDS", "30")
    limiter = build_limiter_from_env()
    assert limiter._max == 7.0  # noqa: SLF001 — verifying env wiring
    assert limiter._window == 30.0  # noqa: SLF001


def test_build_limiter_from_env_defaults(monkeypatch):
    monkeypatch.delenv("SIDEKICK_RATE_LIMIT_MAX", raising=False)
    monkeypatch.delenv("SIDEKICK_RATE_LIMIT_WINDOW_SECONDS", raising=False)
    limiter = build_limiter_from_env()
    assert limiter._max == 10.0  # noqa: SLF001
    assert limiter._window == 60.0  # noqa: SLF001


def test_build_limiter_from_env_ignores_bad_values(monkeypatch):
    monkeypatch.setenv("SIDEKICK_RATE_LIMIT_MAX", "not-a-number")
    monkeypatch.setenv("SIDEKICK_RATE_LIMIT_WINDOW_SECONDS", "-5")
    limiter = build_limiter_from_env()
    assert limiter._max == 10.0  # noqa: SLF001
    assert limiter._window == 60.0  # noqa: SLF001


def test_default_limiter_is_singleton():
    reset_default_limiter()
    try:
        first = get_default_limiter()
        second = get_default_limiter()
        assert first is second
    finally:
        reset_default_limiter()


def test_reset_clears_buckets(monkeypatch):
    monkeypatch.delenv("SIDEKICK_RATE_LIMIT_MAX", raising=False)
    ratelimit.reset_default_limiter()
    limiter = get_default_limiter()
    asyncio.run(limiter.acquire("x"))
    limiter.reset()
    assert limiter._buckets == {}  # noqa: SLF001
    ratelimit.reset_default_limiter()
