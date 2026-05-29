"""Chronary.ai concrete CalendarProvider.

Replaces GoogleCalendarProvider. Maps the MCP tool surface
(list_events / create_event / update_event / delete_event) onto the
Chronary REST API via the official `chronary` Python SDK.

Bootstrap: the agent and default calendar must already exist. Run
`sidekick-init` once after setting CHRONARY_API_KEY — it creates them
and writes the IDs to ~/.config/sidekick/config.json (and prints them
so you can drop them into .env).

Known feature gaps vs Google Calendar:
- Recurring events: not documented in Chronary's REST surface.
- `location` and `attendees`: not first-class fields. We stash them
  in the event's `metadata` dict so they round-trip via Chronary
  without data loss, and surface back on list/get.
"""

import os
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .base import CalendarProvider


def _to_utc_z(dt: datetime) -> str:
    """Format an aware datetime as ``YYYY-MM-DDTHH:MM:SSZ``.

    Chronary's events endpoint only accepts ``Z``-suffixed UTC timestamps;
    offset forms like ``-05:00`` or ``+00:00`` and naive forms are rejected
    with ``400 validation_error``. ``datetime.isoformat()`` emits the offset
    form even when the offset is zero, so we format explicitly.
    """
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_event_datetime(value: str, default_tz: str) -> str:
    """Normalize an ISO 8601 datetime string for the Chronary events API.

    Inputs can come from the LLM (typically ``-05:00`` offset form) or the
    web dashboard's HTML ``<input type="datetime-local">`` (naive form like
    ``2026-05-26T13:00``). Chronary only accepts ``Z``-suffix UTC, so we:

    * pass date-only strings (``YYYY-MM-DD``, no ``T``) through unchanged so
      all-day events still flow into the SDK with ``all_day=True``;
    * parse anything with a ``T``, attach ``default_tz`` if the value is
      naive, and re-emit as ``Z``-suffix UTC.
    """
    if "T" not in value:
        return value
    # ``fromisoformat`` accepts ``Z`` natively on 3.11+.
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(default_tz))
    return _to_utc_z(parsed)


class ChronaryProvider(CalendarProvider):
    def __init__(
        self,
        *,
        client: Any = None,
        agent_id: str | None = None,
        calendar_id: str | None = None,
        timezone: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.agent_id = agent_id or os.environ["CHRONARY_AGENT_ID"]
        self.calendar_id = calendar_id or os.environ["CHRONARY_CALENDAR_ID"]
        self.timezone = timezone or os.getenv("TIMEZONE") or "America/Chicago"
        self.client = client if client is not None else _build_client(api_key)

    def list_events(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        start_date = args["start_date"]
        end_date = args["end_date"]
        max_results = args.get("max_results", 20)

        tz = ZoneInfo(self.timezone)
        start_after = _to_utc_z(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz))
        start_before = _to_utc_z(
            datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=tz
            )
        )

        # Use the calendar-scoped endpoint (``GET /v1/calendars/{cal}/events``)
        # so we see every event in the calendar, not just the subset the
        # agent itself scheduled. The agent-scoped endpoint
        # (``client.agents.events.list``) only returns events the agent owns;
        # events created via the dashboard's ``POST /events`` form go through
        # the calendar endpoint and never appear under the agent.
        result = self.client.events.list(
            self.calendar_id,
            start_after=start_after,
            start_before=start_before,
            limit=max_results,
        )
        # SDK >=0.1.x returns a ``SyncPager`` (not directly iterable); fall back
        # to plain-list for the test doubles that pre-date this API change.
        events = result.data if hasattr(result, "data") else list(result)
        return [_event_to_dict(e) for e in events]

    def create_event(self, args: dict[str, Any]) -> dict[str, Any]:
        # Chronary's API rejects offset and naive datetime forms — normalize
        # to ``Z``-suffix UTC. Date-only strings (all-day events) are passed
        # through unchanged.
        metadata: dict[str, Any] = {}
        if args.get("location"):
            metadata["location"] = args["location"]
        if args.get("attendees"):
            metadata["attendees"] = list(args["attendees"])

        kwargs: dict[str, Any] = {
            "calendar_id": self.calendar_id,
            "title": args["summary"],
            "start_time": _normalize_event_datetime(args["start_datetime"], self.timezone),
            "end_time": _normalize_event_datetime(args["end_datetime"], self.timezone),
        }
        if "description" in args:
            kwargs["description"] = args["description"]
        if metadata:
            kwargs["metadata"] = metadata
        # `all_day` events use plain YYYY-MM-DD; Chronary accepts via all_day flag.
        if "T" not in args["start_datetime"]:
            kwargs["all_day"] = True

        event = self.client.events.create(**kwargs)
        return {
            "id": _attr(event, "id"),
            "summary": _attr(event, "title"),
            "htmlLink": _attr(event, "url") or _attr(event, "html_link"),
        }

    def update_event(self, args: dict[str, Any]) -> dict[str, Any]:
        event_id = args["event_id"]
        kwargs: dict[str, Any] = {}
        if "summary" in args:
            kwargs["title"] = args["summary"]
        if "description" in args:
            kwargs["description"] = args["description"]
        if "start_datetime" in args:
            kwargs["start_time"] = _normalize_event_datetime(args["start_datetime"], self.timezone)
        if "end_datetime" in args:
            kwargs["end_time"] = _normalize_event_datetime(args["end_datetime"], self.timezone)
        if "location" in args or "attendees" in args:
            # Merge into metadata. We don't fetch the existing event first
            # because Chronary's PATCH semantics replace metadata wholesale
            # only if `metadata` is included; partial updates need a read.
            existing = self.client.events.get(calendar_id=self.calendar_id, event_id=event_id)
            metadata = dict(_attr(existing, "metadata") or {})
            if "location" in args:
                metadata["location"] = args["location"]
            if "attendees" in args:
                metadata["attendees"] = list(args["attendees"])
            kwargs["metadata"] = metadata

        updated = self.client.events.update(
            calendar_id=self.calendar_id, event_id=event_id, **kwargs
        )
        return _event_to_dict(updated)

    def delete_event(self, args: dict[str, Any]) -> dict[str, Any]:
        event_id = args["event_id"]
        self.client.events.delete(calendar_id=self.calendar_id, event_id=event_id)
        return {"status": "deleted", "event_id": event_id}


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """SDK responses may be Pydantic models or plain dicts; tolerate both."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _iso_utc(value: Any) -> Any:
    """Coerce a Chronary datetime to a ``Z``-suffix UTC string for JSON output.

    The SDK returns ``start_time``/``end_time`` as aware ``datetime`` objects.
    Those would crash ``json.dumps`` at the MCP boundary (``mcp_server.py``)
    with ``Object of type datetime is not JSON serializable``, so we render
    them in the same ``Z``-UTC form the rest of this module standardizes on.
    Plain strings (older SDK versions and the test doubles) pass through
    untouched.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return _to_utc_z(value)
    return value


def _event_to_dict(event: Any) -> dict[str, Any]:
    metadata = _attr(event, "metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": _attr(event, "id"),
        "summary": _attr(event, "title", "(no title)"),
        "start": _iso_utc(_attr(event, "start_time")),
        "end": _iso_utc(_attr(event, "end_time")),
        "description": _attr(event, "description", ""),
        "location": metadata.get("location", ""),
        "attendees": metadata.get("attendees", []),
    }


def _build_client(api_key: str | None) -> Any:
    """Lazy-import the chronary SDK so tests can run without it installed."""
    from chronary import Chronary

    return Chronary(api_key=api_key or os.environ["CHRONARY_API_KEY"])
