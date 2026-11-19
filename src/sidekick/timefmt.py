"""Render event times in the user's timezone.

Chronary stores and returns every timestamp in UTC (``...Z``). Anything shown
to a person, or handed to the LLM, must be converted to the configured
``TIMEZONE`` first: printing the UTC clock is how a 6:40 PM Pacific game turned
into "2:40 AM" in the morning summary.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def to_local(value: str | datetime, tz_name: str) -> datetime | None:
    """Parse an ISO datetime (or take a ``datetime``) and convert it to ``tz_name``.

    Naive values are taken to already be in ``tz_name``. Returns ``None`` for
    date-only strings (all-day events) and anything unparseable.
    """
    tz = ZoneInfo(tz_name)
    if isinstance(value, datetime):
        dt = value
    else:
        if "T" not in value:
            return None
        try:
            dt = datetime.fromisoformat(value)  # accepts "Z" on 3.11+
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def clock(dt: datetime) -> str:
    """``6:40 PM`` (``%-I`` is GNU-only, so strip the leading zero by hand)."""
    return dt.strftime("%I:%M %p").lstrip("0")


def format_event_span(start: str, end: str | None, tz_name: str, *, all_day: bool = False) -> str:
    """Human-readable local span for a calendar row.

    ``Thu Nov 19, 6:40 PM - 9:40 PM``. When the end falls on another day it
    gets its own date, and all-day or date-only events read as ``Thu Nov 19
    (all day)``.
    """
    start_dt = None if all_day else to_local(start, tz_name)
    if start_dt is None:
        day = start.split("T", 1)[0]
        try:
            return datetime.strptime(day, "%Y-%m-%d").strftime("%a %b %d (all day)")
        except ValueError:
            return start
    text = f"{start_dt.strftime('%a %b %d')}, {clock(start_dt)}"
    end_dt = to_local(end, tz_name) if end else None
    if end_dt is not None:
        same_day = end_dt.date() == start_dt.date()
        text += (
            f" - {clock(end_dt)}"
            if same_day
            else f" - {end_dt.strftime('%a %b %d')}, {clock(end_dt)}"
        )
    return text
