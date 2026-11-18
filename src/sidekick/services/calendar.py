"""Calendar service functions.

Wrap :class:`ChronaryProvider` sync calls in ``run_sync``. Provider is
passed in so tests can substitute a mock without the real Chronary env
vars.

Module name is ``calendar`` because services live in their own package
— it doesn't shadow the stdlib ``calendar`` here the way the web
handler module would.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..util import run_sync


async def list_events(
    provider: Any, *, days: int = 14, max_results: int = 50
) -> list[dict[str, Any]]:
    """List upcoming events in the next ``days`` days (clamped to 1..90)."""
    days = max(1, min(days, 90))
    start = date.today()
    end = start + timedelta(days=days)
    events = await run_sync(
        provider.list_events,
        {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "max_results": max_results,
        },
    )
    return list(events)


async def create_event(
    provider: Any,
    *,
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "summary": summary,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
    }
    if description:
        args["description"] = description
    if location:
        args["location"] = location
    result = await run_sync(provider.create_event, args)
    return dict(result) if isinstance(result, dict) else {"result": result}


async def update_event(provider: Any, event_id: str, **fields: str) -> dict[str, Any]:
    args: dict[str, Any] = {"event_id": event_id}
    for key in ("summary", "description", "location", "start_datetime", "end_datetime"):
        value = fields.get(key)
        if value:
            args[key] = value
    result = await run_sync(provider.update_event, args)
    return dict(result) if isinstance(result, dict) else {"result": result}


async def delete_event(provider: Any, event_id: str) -> dict[str, Any]:
    result = await run_sync(provider.delete_event, {"event_id": event_id})
    return dict(result) if isinstance(result, dict) else {"result": result}
