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
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .base import CalendarProvider


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
        self.timezone = timezone or os.getenv("TIMEZONE", "America/Chicago")
        self.client = client if client is not None else _build_client(api_key)

    def list_events(self, args: dict) -> list[dict]:
        start_date = args["start_date"]
        end_date = args["end_date"]
        max_results = args.get("max_results", 20)

        tz = ZoneInfo(self.timezone)
        start_after = (
            datetime.strptime(start_date, "%Y-%m-%d")
            .replace(tzinfo=tz)
            .isoformat()
        )
        start_before = (
            datetime.strptime(end_date, "%Y-%m-%d")
            .replace(hour=23, minute=59, second=59, tzinfo=tz)
            .isoformat()
        )

        result = self.client.agents.events.list(
            self.agent_id,
            start_after=start_after,
            start_before=start_before,
            limit=max_results,
        )
        return [_event_to_dict(e) for e in result]

    def create_event(self, args: dict) -> dict:
        # Chronary requires ISO 8601 timestamps; passthrough.
        metadata: dict = {}
        if args.get("location"):
            metadata["location"] = args["location"]
        if args.get("attendees"):
            metadata["attendees"] = list(args["attendees"])

        kwargs: dict = {
            "calendar_id": self.calendar_id,
            "title": args["summary"],
            "start_time": args["start_datetime"],
            "end_time": args["end_datetime"],
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

    def update_event(self, args: dict) -> dict:
        event_id = args["event_id"]
        kwargs: dict = {}
        if "summary" in args:
            kwargs["title"] = args["summary"]
        if "description" in args:
            kwargs["description"] = args["description"]
        if "start_datetime" in args:
            kwargs["start_time"] = args["start_datetime"]
        if "end_datetime" in args:
            kwargs["end_time"] = args["end_datetime"]
        if "location" in args or "attendees" in args:
            # Merge into metadata. We don't fetch the existing event first
            # because Chronary's PATCH semantics replace metadata wholesale
            # only if `metadata` is included; partial updates need a read.
            existing = self.client.events.get(
                calendar_id=self.calendar_id, event_id=event_id
            )
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

    def delete_event(self, args: dict) -> dict:
        event_id = args["event_id"]
        self.client.events.delete(calendar_id=self.calendar_id, event_id=event_id)
        return {"status": "deleted", "event_id": event_id}


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """SDK responses may be Pydantic models or plain dicts; tolerate both."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _event_to_dict(event: Any) -> dict:
    metadata = _attr(event, "metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": _attr(event, "id"),
        "summary": _attr(event, "title", "(no title)"),
        "start": _attr(event, "start_time"),
        "end": _attr(event, "end_time"),
        "description": _attr(event, "description", ""),
        "location": metadata.get("location", ""),
        "attendees": metadata.get("attendees", []),
    }


def _build_client(api_key: str | None) -> Any:
    """Lazy-import the chronary SDK so tests can run without it installed."""
    from chronary import Chronary  # type: ignore[import-not-found]

    return Chronary(api_key=api_key or os.environ["CHRONARY_API_KEY"])
