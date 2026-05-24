"""
MCP server exposing Chronary calendar + local SQLite task store as tools.

Exposes twelve tools to Claude:
  - list_events, create_event, update_event, delete_event   (Chronary)
  - list_task_lists, list_tasks, add_tasks, complete_task,
    delete_task, clear_completed, delete_task_list, rename_task_list
                                                            (SQLite)
"""

import asyncio
import json
import os
from typing import Any

import mcp.types as types
from mcp.server import Server

from .calendar.chronary import ChronaryProvider
from .storage.sqlite_tasks import SQLiteTaskStore


class MCPServer:
    def __init__(self) -> None:
        self.timezone = os.getenv("TIMEZONE", "America/Chicago")
        self._calendar: ChronaryProvider | None = None
        self._tasks_store: SQLiteTaskStore | None = None
        self.server = Server("sidekick")
        self._register_tools()

    # ------------------------------------------------------------------
    # Provider accessors — calendar pulls IDs from env (set by
    # `sidekick-init`); task store opens a local SQLite database at
    # SIDEKICK_DB_PATH (default ~/.config/sidekick/sidekick.db).
    # ------------------------------------------------------------------

    @property
    def calendar(self) -> ChronaryProvider:
        if self._calendar is None:
            self._calendar = ChronaryProvider(timezone=self.timezone)
        return self._calendar

    @property
    def tasks_store(self) -> SQLiteTaskStore:
        if self._tasks_store is None:
            self._tasks_store = SQLiteTaskStore()
        return self._tasks_store

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        @self.server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
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
                                "description": "The calendar event ID",
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
                                "description": "The calendar event ID to delete",
                            }
                        },
                        "required": ["event_id"],
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

        @self.server.call_tool()  # type: ignore[untyped-decorator]
        async def handle_call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[types.TextContent]:
            args = arguments or {}
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self._dispatch, name, args
                )
                return [types.TextContent(type="text", text=json.dumps(result))]
            except Exception as e:
                import logging

                logging.getLogger(__name__).error(
                    "Unexpected error calling %s: %s", name, e, exc_info=True
                )
                error = {"error": str(e)}
                return [types.TextContent(type="text", text=json.dumps(error))]

    def _dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        """Synchronous dispatch to the appropriate provider call."""
        dispatch: dict[str, Any] = {
            "list_events": self._list_events,
            "create_event": self._create_event,
            "update_event": self._update_event,
            "delete_event": self._delete_event,
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
            result: dict[str, Any] | list[dict[str, Any]] = handler(args)
            return result
        return {"error": f"Unknown tool: {name}"}

    # ------------------------------------------------------------------
    # Tool implementations — delegate to providers.
    # ------------------------------------------------------------------

    def _list_events(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        return self.calendar.list_events(args)

    def _create_event(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.calendar.create_event(args)

    def _update_event(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.calendar.update_event(args)

    def _delete_event(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.calendar.delete_event(args)

    # Helpers kept so tests / external callers can poke at the store
    def _find_task_list(self, list_name: str) -> int | None:
        return self.tasks_store.find_task_list(list_name)

    def _get_or_create_task_list(self, list_name: str) -> int:
        return self.tasks_store.get_or_create_task_list(list_name)

    def _find_task_by_title(self, list_id: int, title: str) -> dict[str, Any] | None:
        return self.tasks_store.find_task_by_title(list_id, title)

    def _list_tasks(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        return self.tasks_store.list_tasks(args)

    def _add_tasks(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.tasks_store.add_tasks(args)

    def _complete_task(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.tasks_store.complete_task(args)

    def _delete_task(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.tasks_store.delete_task(args)

    def _clear_completed(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.tasks_store.clear_completed(args)

    def _list_task_lists(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        return self.tasks_store.list_task_lists(args)

    def _delete_task_list(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.tasks_store.delete_task_list(args)

    def _rename_task_list(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.tasks_store.rename_task_list(args)


if __name__ == "__main__":
    import asyncio

    from mcp.server.stdio import stdio_server

    async def _serve() -> None:
        server: MCPServer = MCPServer()
        async with stdio_server() as (read_stream, write_stream):
            await server.server.run(
                read_stream,
                write_stream,
                server.server.create_initialization_options(),
            )

    asyncio.run(_serve())
