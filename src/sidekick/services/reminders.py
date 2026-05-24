"""Reminder service functions.

Delegate to the existing module-level helpers in
:mod:`sidekick.reminders`. The scheduler is in-process so these
mutations take effect immediately on the running scheduler.
"""

from __future__ import annotations

from typing import Any

from ..reminders import (
    BUILTIN_IDS,
    get_all_reminders,
)
from ..reminders import (
    add_reminder as _add_reminder,
)
from ..reminders import (
    remove_reminder as _remove_reminder,
)
from ..reminders import (
    update_reminder as _update_reminder,
)
from ..util import run_sync


async def list_all(scheduler: Any) -> list[dict[str, Any]]:
    """Return every active job plus disabled custom reminders from disk."""
    reminders = await run_sync(get_all_reminders, scheduler)
    return list(reminders)


async def create(
    scheduler: Any,
    agent: Any,
    *,
    message: str,
    hour: int,
    minute: int,
    chat_id: int = 0,
    day_of_week: str | None = None,
) -> dict[str, Any]:
    result = await run_sync(
        _add_reminder, scheduler, agent, message, hour, minute, chat_id, day_of_week
    )
    return dict(result)


async def update(
    scheduler: Any,
    agent: Any,
    reminder_id: str,
    *,
    message: str | None = None,
    hour: int | None = None,
    minute: int | None = None,
    day_of_week: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    result = await run_sync(
        _update_reminder,
        scheduler,
        agent,
        reminder_id,
        message,
        hour,
        minute,
        day_of_week,
        enabled,
    )
    return dict(result)


async def delete(scheduler: Any, reminder_id: str) -> dict[str, Any]:
    if reminder_id in BUILTIN_IDS:
        return {
            "error": (
                f"Built-in reminder '{reminder_id}' cannot be removed; "
                "disable it via update instead."
            )
        }
    result = await run_sync(_remove_reminder, scheduler, reminder_id)
    return dict(result)


__all__ = ["BUILTIN_IDS", "list_all", "create", "update", "delete"]
