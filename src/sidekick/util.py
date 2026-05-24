"""Cross-cutting utilities used by both services and web handlers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


async def run_sync(fn: Callable[..., T], *args: Any) -> T:
    """Run a sync provider/store call in the default thread executor.

    Mirrors the ``MCPServer._dispatch`` pattern so synchronous SQLite /
    Chronary calls don't block the shared event loop.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)
