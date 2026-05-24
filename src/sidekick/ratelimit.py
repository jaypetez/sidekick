"""Async-safe per-key token bucket rate limiter.

Used by every chat surface (Telegram, Slack, web ``/chat``) to cap how
many requests a single user / session can make per window. Buckets are
held in-process — the bot is a single instance, so this is sufficient
without pulling in Redis or similar.

Configuration is environment-driven so operators can tune without code
changes::

    SIDEKICK_RATE_LIMIT_MAX=10               # max requests per window
    SIDEKICK_RATE_LIMIT_WINDOW_SECONDS=60    # window length in seconds

Usage::

    limiter = get_default_limiter()
    if not await limiter.acquire(user_key):
        return  # over budget — caller decides how to reject
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class RateLimiter:
    """In-process token bucket keyed by an arbitrary hashable identifier.

    The bucket fills linearly: ``max_requests`` tokens accumulate over
    ``window_seconds``. ``acquire()`` consumes one token and returns
    False when the bucket is empty.
    """

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max = float(max_requests)
        self._window = float(window_seconds)
        self._refill_per_sec = self._max / self._window
        self._buckets: dict[object, _Bucket] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: object) -> bool:
        """Try to consume one token for ``key``. Returns False if empty."""
        now = time.monotonic()
        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self._max, updated_at=now)
                self._buckets[key] = bucket
            else:
                elapsed = max(0.0, now - bucket.updated_at)
                bucket.tokens = min(self._max, bucket.tokens + elapsed * self._refill_per_sec)
                bucket.updated_at = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True
            return False

    def reset(self) -> None:
        """Drop all buckets — primarily a test hook."""
        self._buckets.clear()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def build_limiter_from_env() -> RateLimiter:
    """Construct a RateLimiter from ``SIDEKICK_RATE_LIMIT_*`` env vars."""
    return RateLimiter(
        max_requests=_env_int("SIDEKICK_RATE_LIMIT_MAX", 10),
        window_seconds=_env_int("SIDEKICK_RATE_LIMIT_WINDOW_SECONDS", 60),
    )


_default_limiter: RateLimiter | None = None


def get_default_limiter() -> RateLimiter:
    """Process-wide shared limiter. Lazy so env overrides are honoured."""
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = build_limiter_from_env()
    return _default_limiter


def reset_default_limiter() -> None:
    """Test hook: forget the cached singleton so env changes take effect."""
    global _default_limiter
    _default_limiter = None
