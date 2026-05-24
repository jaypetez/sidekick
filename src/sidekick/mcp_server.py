"""
MCP server wrapping Google Calendar, Gmail, and Google Tasks APIs.

Exposes thirteen tools to Claude:
  - list_events, create_event, update_event, delete_event
  - send_email
  - list_task_lists, list_tasks, add_tasks, complete_task, delete_task,
    clear_completed, delete_task_list, rename_task_list
"""

import asyncio
import base64
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from mcp.server import Server
import mcp.types as types

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/tasks",
]


class MCPServer:
    def __init__(self):
        self.service = None
        self.gmail = None
        self.tasks = None
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
        self.timezone = os.getenv("TIMEZONE", "America/Chicago")
        self.server = Server("sidekick")
        self._register_tools()

    # ------------------------------------------------------------------
    # Google Auth
    # ------------------------------------------------------------------

    def build_google_service(self) -> None:
        """Load OAuth2 token and build the Calendar service.

        token.json must already exist — generate it on your laptop by
        running auth.py, then SCP it to ~/.config/sidekick/token.json.
        The token auto-refreshes when expired.
        """
        token_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
        creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

        if not os.path.exists(token_file):
            raise FileNotFoundError(
                f"token.json not found at {token_file}.\n"
                "Run auth.py on your laptop to generate it, then SCP it to this server.\n"
                "See README.md for instructions."
            )

        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w") as f:
                f.write(creds.to_json())

        self.service = build("calendar", "v3", credentials=creds)
        self.gmail = build("gmail", "v1", credentials=creds)
        self.tasks = build("tasks", "v1", credentials=creds)

    # ------------------------------------------------------------------
    # Tool helpers
    # ------------------------------------------------------------------

    def _event_to_dict(self, event: dict) -> dict:
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

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        @self.server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name="list_events",
                    description="List upcoming calendar events in a date range.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "start_date": {
                                "type": "string",
                                "description": "Start date in ISO format (YYYY-MM-DD)",
                            },
                            "end_date": {
                                "type": "string",
                                "description": "End date in ISO format (YYYY-MM-DD)",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of events to return (default 20)",
                                "default": 20,
                            },
                        },
                        "required": ["start_date", "end_date"],
                    },
                ),
                types.Tool(
                    name="create_event",
                    description="Create a new calendar event.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "string",
                                "description": "Event title",
                            },
                            "start_datetime": {
                                "type": "string",
                                "description": "Start date/time in ISO 8601 format with timezone (e.g. 2026-03-25T14:00:00-06:00). For all-day events use YYYY-MM-DD.",
                            },
                            "end_datetime": {
                                "type": "string",
                                "description": "End date/time in ISO 8601 format with timezone. For all-day events use YYYY-MM-DD.",
                            },
                            "description": {
                                "type": "string",
                                "description": "Event description (optional)",
                            },
                            "location": {
                                "type": "string",
                                "description": "Event location (optional)",
                            },
                            "attendees": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of attendee email addresses (optional)",
                            },
                        },
                        "required": ["summary", "start_datetime", "end_datetime"],
                    },
                ),
                types.Tool(
                    name="update_event",
                    description="Update an existing calendar event. Provide the event_id and only the fields you want to change.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "event_id": {
                                "type": "string",
                                "description": "The Google Calendar event ID",
                            },
                            "summary": {"type": "string"},
                            "start_datetime": {"type": "string"},
                            "end_datetime": {"type": "string"},
                            "description": {"type": "string"},
                            "location": {"type": "string"},
                        },
                        "required": ["event_id"],
                    },
                ),
                types.Tool(
                    name="delete_event",
                    description="Delete a calendar event by its ID.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "event_id": {
                                "type": "string",
                                "description": "The Google Calendar event ID to delete",
                            }
                        },
                        "required": ["event_id"],
                    },
                ),
                types.Tool(
                    name="send_email",
                    description="Send an email via Gmail.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "to": {
                                "type": "string",
                                "description": "Recipient email address",
                            },
                            "subject": {
                                "type": "string",
                                "description": "Email subject line",
                            },
                            "body": {
                                "type": "string",
                                "description": "Plain text email body",
                            },
                        },
                        "required": ["to", "subject", "body"],
                    },
                ),
                types.Tool(
                    name="list_task_lists",
                    description="List all task lists. Use this to discover what lists exist before creating duplicates.",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                types.Tool(
                    name="list_tasks",
                    description="List incomplete tasks from a task list.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "list_name": {
                                "type": "string",
                                "description": "Name of the task list (e.g. 'Costco', 'Home Renovation', 'To-Do')",
                            },
                        },
                        "required": ["list_name"],
                    },
                ),
                types.Tool(
                    name="add_tasks",
                    description="Add one or more tasks to a task list. The list is created automatically if it doesn't exist.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "list_name": {
                                "type": "string",
                                "description": "Name of the task list (e.g. 'Costco', 'Home Renovation', 'To-Do')",
                            },
                            "items": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of task titles to add",
                            },
                        },
                        "required": ["list_name", "items"],
                    },
                ),
                types.Tool(
                    name="complete_task",
                    description="Mark a task as completed by its title (case-insensitive partial match).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "list_name": {
                                "type": "string",
                                "description": "Name of the task list",
                            },
                            "task_title": {
                                "type": "string",
                                "description": "Title (or partial title) of the task to complete",
                            },
                        },
                        "required": ["list_name", "task_title"],
                    },
                ),
                types.Tool(
                    name="delete_task",
                    description="Delete a task entirely by its title (case-insensitive partial match).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "list_name": {
                                "type": "string",
                                "description": "Name of the task list",
                            },
                            "task_title": {
                                "type": "string",
                                "description": "Title (or partial title) of the task to delete",
                            },
                        },
                        "required": ["list_name", "task_title"],
                    },
                ),
                types.Tool(
                    name="clear_completed",
                    description="Remove all completed tasks from a task list.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "list_name": {
                                "type": "string",
                                "description": "Name of the task list",
                            },
                        },
                        "required": ["list_name"],
                    },
                ),
                types.Tool(
                    name="delete_task_list",
                    description="Delete an entire task list and all its tasks.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "list_name": {
                                "type": "string",
                                "description": "Name of the task list to delete",
                            },
                        },
                        "required": ["list_name"],
                    },
                ),
                types.Tool(
                    name="rename_task_list",
                    description="Rename an existing task list.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "list_name": {
                                "type": "string",
                                "description": "Current name of the task list",
                            },
                            "new_name": {
                                "type": "string",
                                "description": "New name for the task list",
                            },
                        },
                        "required": ["list_name", "new_name"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict | None
        ) -> list[types.TextContent]:
            args = arguments or {}
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self._dispatch, name, args
                )
                return [types.TextContent(type="text", text=json.dumps(result))]
            except HttpError as e:
                import logging
                logging.getLogger(__name__).error(
                    "Google API error calling %s: %s %s", name, e.resp.status, e.reason
                )
                error = {"error": str(e.reason), "code": e.resp.status}
                return [types.TextContent(type="text", text=json.dumps(error))]
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(
                    "Unexpected error calling %s: %s", name, e, exc_info=True
                )
                error = {"error": str(e)}
                return [types.TextContent(type="text", text=json.dumps(error))]

    def _dispatch(self, name: str, args: dict) -> dict | list:
        """Synchronous dispatch to the appropriate API call."""
        dispatch = {
            "list_events": self._list_events,
            "create_event": self._create_event,
            "update_event": self._update_event,
            "delete_event": self._delete_event,
            "send_email": self._send_email,
            "list_task_lists": self._list_task_lists,
            "list_tasks": self._list_tasks,
            "add_tasks": self._add_tasks,
            "complete_task": self._complete_task,
            "delete_task": self._delete_task,
            "clear_completed": self._clear_completed,
            "delete_task_list": self._delete_task_list,
            "rename_task_list": self._rename_task_list,
        }
        handler = dispatch.get(name)
        if handler:
            return handler(args)
        return {"error": f"Unknown tool: {name}"}

    # ------------------------------------------------------------------
    # Google Calendar operations (synchronous, run in executor)
    # ------------------------------------------------------------------

    def _list_events(self, args: dict) -> list:
        start_date = args["start_date"]
        end_date = args["end_date"]
        max_results = args.get("max_results", 20)

        # Convert date strings to RFC3339 timestamps in the user's timezone
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
        return [self._event_to_dict(e) for e in result.get("items", [])]

    def _create_event(self, args: dict) -> dict:
        start = args["start_datetime"]
        end = args["end_datetime"]

        # Detect all-day events (no time component)
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

    def _update_event(self, args: dict) -> dict:
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
        return self._event_to_dict(updated)

    def _delete_event(self, args: dict) -> dict:
        event_id = args["event_id"]
        self.service.events().delete(
            calendarId=self.calendar_id, eventId=event_id
        ).execute()
        return {"status": "deleted", "event_id": event_id}

    def _send_email(self, args: dict) -> dict:
        message = MIMEMultipart()
        message["to"] = args["to"]
        message["subject"] = args["subject"]
        message.attach(MIMEText(args["body"], "plain"))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        result = self.gmail.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return {"status": "sent", "message_id": result.get("id")}

    # ------------------------------------------------------------------
    # Google Tasks operations (synchronous, run in executor)
    # ------------------------------------------------------------------

    def _find_task_list(self, list_name: str) -> str | None:
        """Find a task list by name (case-insensitive). Returns the list ID or None."""
        result = self.tasks.tasklists().list().execute()
        for tl in result.get("items", []):
            if tl["title"].lower() == list_name.lower():
                return tl["id"]
        return None

    def _get_or_create_task_list(self, list_name: str) -> str:
        """Find a task list by name, or create it. Returns the list ID."""
        list_id = self._find_task_list(list_name)
        if list_id:
            return list_id
        new_list = self.tasks.tasklists().insert(
            body={"title": list_name}
        ).execute()
        return new_list["id"]

    def _find_task_by_title(self, list_id: str, title: str) -> dict | None:
        """Find the first incomplete task matching title (case-insensitive partial match)."""
        result = self.tasks.tasks().list(
            tasklist=list_id, showCompleted=False
        ).execute()
        title_lower = title.lower()
        for task in result.get("items", []):
            if title_lower in task.get("title", "").lower():
                return task
        return None

    def _list_tasks(self, args: dict) -> list:
        list_id = self._get_or_create_task_list(args["list_name"])
        result = self.tasks.tasks().list(
            tasklist=list_id, showCompleted=False
        ).execute()
        return [
            {"title": t.get("title", ""), "status": t.get("status", "")}
            for t in result.get("items", [])
        ]

    def _add_tasks(self, args: dict) -> dict:
        list_id = self._get_or_create_task_list(args["list_name"])
        added = []
        for item in args["items"]:
            task = self.tasks.tasks().insert(
                tasklist=list_id, body={"title": item}
            ).execute()
            added.append(task.get("title", ""))
        return {"status": "added", "items": added, "list": args["list_name"]}

    def _complete_task(self, args: dict) -> dict:
        list_id = self._get_or_create_task_list(args["list_name"])
        task = self._find_task_by_title(list_id, args["task_title"])
        if not task:
            return {"error": f"No task matching '{args['task_title']}' found in {args['list_name']}"}
        task["status"] = "completed"
        self.tasks.tasks().update(
            tasklist=list_id, task=task["id"], body=task
        ).execute()
        return {"status": "completed", "title": task["title"]}

    def _delete_task(self, args: dict) -> dict:
        list_id = self._get_or_create_task_list(args["list_name"])
        task = self._find_task_by_title(list_id, args["task_title"])
        if not task:
            return {"error": f"No task matching '{args['task_title']}' found in {args['list_name']}"}
        self.tasks.tasks().delete(
            tasklist=list_id, task=task["id"]
        ).execute()
        return {"status": "deleted", "title": task["title"]}

    def _clear_completed(self, args: dict) -> dict:
        list_id = self._get_or_create_task_list(args["list_name"])
        self.tasks.tasks().clear(tasklist=list_id).execute()
        return {"status": "cleared", "list": args["list_name"]}

    def _list_task_lists(self, args: dict) -> list:
        result = self.tasks.tasklists().list().execute()
        return [
            {"title": tl.get("title", ""), "id": tl.get("id", "")}
            for tl in result.get("items", [])
        ]

    def _delete_task_list(self, args: dict) -> dict:
        list_id = self._find_task_list(args["list_name"])
        if not list_id:
            return {"error": f"Task list '{args['list_name']}' not found"}
        self.tasks.tasklists().delete(tasklist=list_id).execute()
        return {"status": "deleted", "list": args["list_name"]}

    def _rename_task_list(self, args: dict) -> dict:
        list_id = self._find_task_list(args["list_name"])
        if not list_id:
            return {"error": f"Task list '{args['list_name']}' not found"}
        self.tasks.tasklists().patch(
            tasklist=list_id, body={"title": args["new_name"]}
        ).execute()
        return {"status": "renamed", "old_name": args["list_name"], "new_name": args["new_name"]}


if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server

    async def _serve() -> None:
        cal = MCPServer()
        cal.build_google_service()
        async with stdio_server() as (read_stream, write_stream):
            await cal.server.run(
                read_stream,
                write_stream,
                cal.server.create_initialization_options(),
            )

    asyncio.run(_serve())
