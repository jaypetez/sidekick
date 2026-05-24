"""Google Calendar concrete provider.

Holds the synchronous Google Calendar v3 API logic that previously
lived directly in `mcp_server.MCPServer`. The MCP server now
instantiates this and delegates. Step 3 replaces it with
ChronaryProvider.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from .base import CalendarProvider


class GoogleCalendarProvider(CalendarProvider):
    def __init__(self, service, calendar_id: str | None = None, timezone: str | None = None) -> None:
        self.service = service
        self.calendar_id = calendar_id or os.getenv("GOOGLE_CALENDAR_ID", "primary")
        self.timezone = timezone or os.getenv("TIMEZONE", "America/Chicago")

    def list_events(self, args: dict) -> list[dict]:
        start_date = args["start_date"]
        end_date = args["end_date"]
        max_results = args.get("max_results", 20)

        tz = ZoneInfo(self.timezone)
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=tz
        )
        time_min = start_dt.isoformat()
        time_max = end_dt.isoformat()

        result = (
            self.service.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return [_event_to_dict(e) for e in result.get("items", [])]

    def create_event(self, args: dict) -> dict:
        start = args["start_datetime"]
        end = args["end_datetime"]

        if "T" in start:
            start_obj = {"dateTime": start}
            end_obj = {"dateTime": end}
        else:
            start_obj = {"date": start}
            end_obj = {"date": end}

        body: dict = {
            "summary": args["summary"],
            "start": start_obj,
            "end": end_obj,
        }
        if "description" in args:
            body["description"] = args["description"]
        if "location" in args:
            body["location"] = args["location"]
        if "attendees" in args:
            body["attendees"] = [{"email": e} for e in args["attendees"]]

        event = (
            self.service.events()
            .insert(calendarId=self.calendar_id, body=body)
            .execute()
        )
        return {
            "id": event["id"],
            "summary": event.get("summary"),
            "htmlLink": event.get("htmlLink"),
        }

    def update_event(self, args: dict) -> dict:
        event_id = args["event_id"]
        event = (
            self.service.events()
            .get(calendarId=self.calendar_id, eventId=event_id)
            .execute()
        )

        if "summary" in args:
            event["summary"] = args["summary"]
        if "description" in args:
            event["description"] = args["description"]
        if "location" in args:
            event["location"] = args["location"]
        if "start_datetime" in args:
            start = args["start_datetime"]
            event["start"] = (
                {"dateTime": start} if "T" in start else {"date": start}
            )
        if "end_datetime" in args:
            end = args["end_datetime"]
            event["end"] = {"dateTime": end} if "T" in end else {"date": end}

        updated = (
            self.service.events()
            .update(calendarId=self.calendar_id, eventId=event_id, body=event)
            .execute()
        )
        return _event_to_dict(updated)

    def delete_event(self, args: dict) -> dict:
        event_id = args["event_id"]
        self.service.events().delete(
            calendarId=self.calendar_id, eventId=event_id
        ).execute()
        return {"status": "deleted", "event_id": event_id}


def _event_to_dict(event: dict) -> dict:
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "id": event.get("id"),
        "summary": event.get("summary", "(no title)"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "description": event.get("description", ""),
        "location": event.get("location", ""),
    }
