"""Chronary webhook handling: verify, parse, dedupe, and format reminders.

Chronary can *push* an ``event.reminder`` webhook a set number of minutes
before each confirmed event (per-event ``reminders`` or the calendar's
``default_reminders``), instead of Sidekick polling every 5 minutes.

Wire format (docs.chronary.ai/api-reference/webhooks):

* Body: a flat JSON payload —
  ``event_id, calendar_id, title, start_time, end_time, reminder_minutes``
  and ``occurrence_start`` for recurring instances.
* Headers: ``X-Chronary-Event-Type``, ``X-Delivery-Id`` (stable across
  retries — the idempotency key), ``X-Timestamp`` + ``X-Signature``
  (HMAC-SHA256 over ``{timestamp}.{body}``), ``X-Chronary-Test: 1`` on
  test sends.
* Success is any 2xx within 10 s; anything else is retried with backoff.
* Subscriptions are org-wide, so deliveries for *other* calendars arrive
  too and must be ignored.

This module is framework-free; ``web/handlers/webhooks.py`` adapts it to
aiohttp.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhooks/chronary"
REMINDER_EVENT_TYPE = "event.reminder"

# Chronary's documented replay window; the SDK default is the same.
SIGNATURE_TOLERANCE_SECONDS = 300

# Deliveries are tiny; anything bigger is not from Chronary.
MAX_BODY_BYTES = 64 * 1024

# Chronary retries for up to ~12 h on paid plans; keep ids well past that.
DELIVERY_RETENTION_SECONDS = 7 * 24 * 3600


class InvalidPayload(ValueError):
    """Signature was valid but the body isn't a reminder we can use."""


@dataclass(frozen=True)
class ReminderNotice:
    delivery_id: str
    event_id: str
    calendar_id: str | None
    title: str
    start_time: datetime
    reminder_minutes: int | None
    occurrence_start: str | None
    is_test: bool


def _header(headers: Mapping[str, str], name: str) -> str | None:
    value = headers.get(name)
    if value is None:
        lowered = name.lower()
        for key, val in headers.items():
            if key.lower() == lowered:
                return val
    return value


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise InvalidPayload("start_time missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidPayload(f"start_time not ISO-8601: {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_reminder(
    payload: bytes,
    headers: Mapping[str, str],
    *,
    secret: str,
    calendar_id: str | None,
) -> ReminderNotice | None:
    """Verify a delivery and return the reminder it carries.

    Raises ``chronary.SignatureVerificationError`` for a missing, stale or
    forged signature and :class:`InvalidPayload` for a signed body we can't
    use. Returns ``None`` for deliveries that are authentic but not for us:
    another event type, or another calendar in the same Chronary org.
    """
    from chronary.webhook import verify_signature

    verify_signature(payload, headers, secret=secret, tolerance=SIGNATURE_TOLERANCE_SECONDS)

    # The event-type header is *not* covered by the signature; only the body
    # is. That's fine: a forged type can only make us ignore a delivery, and
    # the body still has to parse as a reminder below.
    if _header(headers, "X-Chronary-Event-Type") != REMINDER_EVENT_TYPE:
        return None

    try:
        data: Any = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidPayload("body is not JSON") from exc
    if not isinstance(data, dict):
        raise InvalidPayload("body is not a JSON object")

    delivered_calendar = data.get("calendar_id")
    if calendar_id and delivered_calendar and delivered_calendar != calendar_id:
        return None

    event_id = data.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise InvalidPayload("event_id missing")
    start_time = _parse_time(data.get("start_time"))
    minutes = data.get("reminder_minutes")
    reminder_minutes = (
        minutes if isinstance(minutes, int) and not isinstance(minutes, bool) else None
    )
    occurrence = data.get("occurrence_start")

    delivery_id = _header(headers, "X-Delivery-Id") or (
        # Older deliveries without the header: derive a key that is stable
        # across retries but distinct per reminder offset.
        f"{event_id}:{occurrence or start_time.isoformat()}:{reminder_minutes}"
    )
    title = data.get("title")
    return ReminderNotice(
        delivery_id=delivery_id,
        event_id=event_id,
        calendar_id=delivered_calendar if isinstance(delivered_calendar, str) else None,
        title=title if isinstance(title, str) and title.strip() else "(untitled)",
        start_time=start_time,
        reminder_minutes=reminder_minutes,
        occurrence_start=occurrence if isinstance(occurrence, str) else None,
        is_test=_header(headers, "X-Chronary-Test") == "1",
    )


def _lead_time(minutes: int | None, start: datetime, now: datetime) -> str:
    if minutes is None:
        minutes = max(0, round((start - now).total_seconds() / 60))
    if minutes < 60:
        return f"in {minutes} minute{'s' if minutes != 1 else ''}"
    if minutes < 1440 and minutes % 60 == 0:
        hours = minutes // 60
        return f"in {hours} hour{'s' if hours != 1 else ''}"
    if minutes % 1440 == 0:
        days = minutes // 1440
        return "tomorrow" if days == 1 else f"in {days} days"
    return f"in {minutes} minutes"


def format_reminder(
    notice: ReminderNotice, tz_name: str, *, now: datetime | None = None
) -> tuple[str, str]:
    """Return ``(markdown_v2, plain_text)`` for the reminder message."""
    from .telegram_format import escape_v2

    tz = ZoneInfo(tz_name)
    local = notice.start_time.astimezone(tz)
    current = (now or datetime.now(tz)).astimezone(tz)
    clock = local.strftime("%I:%M %p").lstrip("0")
    when = clock if local.date() == current.date() else f"{local:%a %b} {local.day}, {clock}"
    lead = _lead_time(notice.reminder_minutes, notice.start_time, current)
    prefix = "[test] " if notice.is_test else ""

    plain = f"{prefix}⏰ {notice.title} starts {lead} ({when})"
    v2 = (
        f"{escape_v2(prefix)}⏰ *{escape_v2(notice.title)}* starts {escape_v2(lead)} "
        f"\\({escape_v2(when)}\\)"
    )
    return v2, plain


def _default_db_path() -> str:
    return os.getenv("SIDEKICK_DB_PATH", os.path.expanduser("~/.config/sidekick/sidekick.db"))


class DeliveryLog:
    """Durable record of processed delivery ids (survives restarts).

    Chronary retries a delivery with the same ``X-Delivery-Id`` until it gets
    a 2xx; recording ids here makes those retries (and restarts in between)
    harmless. Lives in the main SQLite DB on its own connection.
    """

    def __init__(self, db_path: str | None = None, *, conn: sqlite3.Connection | None = None):
        if conn is None:
            path = db_path or _default_db_path()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False)
        self._conn = conn
        self._lock = threading.Lock()
        self.last_received_at: datetime | None = None
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS webhook_deliveries ("
                " delivery_id TEXT PRIMARY KEY,"
                " received_at REAL NOT NULL)"
            )

    def record(self, delivery_id: str) -> bool:
        """Record ``delivery_id``; ``True`` if it is new, ``False`` if seen before."""
        now = time.time()
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO webhook_deliveries (delivery_id, received_at) VALUES (?, ?)",
                (delivery_id, now),
            )
            self._conn.execute(
                "DELETE FROM webhook_deliveries WHERE received_at < ?",
                (now - DELIVERY_RETENTION_SECONDS,),
            )
            return cursor.rowcount == 1

    def mark_received(self) -> None:
        self.last_received_at = datetime.now(UTC)
