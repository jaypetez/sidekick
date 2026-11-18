"""Cross-cutting utilities used by both services and web handlers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


def watch_task(task: asyncio.Task[T], name: str) -> asyncio.Task[T]:
    """Log a background task's crash the moment it happens.

    Without a done-callback, an exception in a fire-and-forget task (the web
    server failing to bind its port, a bad Slack token) is only reported as
    "Task exception was never retrieved" when the task is garbage-collected,
    if at all — the feature just silently isn't there.
    """

    def _report(t: asyncio.Task[T]) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("Background task %r crashed", name, exc_info=exc)

    task.add_done_callback(_report)
    return task


async def run_sync(fn: Callable[..., T], *args: Any) -> T:
    """Run a sync provider/store call in the default thread executor.

    Mirrors the ``MCPServer._dispatch`` pattern so synchronous SQLite /
    Chronary calls don't block the shared event loop.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)
