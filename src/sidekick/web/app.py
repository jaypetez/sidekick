"""aiohttp Application factory for the admin dashboard.

The factory takes a reference to the live ``bot_data`` dict (the same one
PTB exposes on its ``Application``) so handlers can reach the running
scheduler, agent, and MCP session without IPC. A ``run_sync`` helper wraps
synchronous provider calls in ``loop.run_in_executor`` to keep the shared
event loop responsive — the same pattern ``MCPServer._dispatch`` uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp_jinja2
import jinja2
from aiohttp import web

from ..calendar.chronary import ChronaryProvider
from ..storage.sqlite_tasks import SQLiteTaskStore
from .handlers import calendar_routes, dashboard, health, reminders, settings, tasks


def make_app(
    *,
    bot_data: dict[str, Any],
    task_store: SQLiteTaskStore | None = None,
    calendar_provider: ChronaryProvider | None = None,
) -> web.Application:
    """Build a configured aiohttp Application for the dashboard.

    ``bot_data`` is shared by reference with PTB, so updates to scheduler,
    agent, MCP state etc. are visible immediately. ``task_store`` is a
    dedicated SQLite connection for the web layer — multiple readers /
    one writer is fine under WAL.
    """
    app = web.Application()
    app["bot_data"] = bot_data
    app["task_store"] = task_store if task_store is not None else SQLiteTaskStore()
    # Calendar provider is constructed lazily — ChronaryProvider's __init__
    # reads CHRONARY_* env vars and would fail in tests without them. The
    # caller (production: bot.py; tests: fixture) passes one in explicitly.
    app["calendar"] = calendar_provider

    templates_dir = Path(__file__).parent / "templates"
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(str(templates_dir)))

    static_dir = Path(__file__).parent / "static"
    app.router.add_static("/static/", path=static_dir, name="static")

    app.router.add_get("/", dashboard.home, name="home")
    app.router.add_get("/health", health.health, name="health")

    app.router.add_get("/reminders", reminders.index, name="reminders.index")
    app.router.add_post("/reminders", reminders.create, name="reminders.create")
    app.router.add_post("/reminders/{id}", reminders.update, name="reminders.update")
    app.router.add_post("/reminders/{id}/delete", reminders.delete, name="reminders.delete")

    app.router.add_get("/tasks", tasks.index, name="tasks.index")
    app.router.add_get("/tasks/{list_name}", tasks.detail, name="tasks.detail")
    app.router.add_post("/tasks/{list_name}/items", tasks.add_item, name="tasks.add_item")
    app.router.add_post(
        "/tasks/{list_name}/items/{title}/complete",
        tasks.complete_item,
        name="tasks.complete_item",
    )
    app.router.add_post(
        "/tasks/{list_name}/items/{title}/delete",
        tasks.delete_item,
        name="tasks.delete_item",
    )
    app.router.add_post(
        "/tasks/{list_name}/clear-completed",
        tasks.clear_completed,
        name="tasks.clear_completed",
    )
    app.router.add_post("/tasks/{list_name}/delete", tasks.delete_list, name="tasks.delete_list")

    app.router.add_get("/events", calendar_routes.index, name="calendar.index")
    app.router.add_post("/events", calendar_routes.create, name="calendar.create")
    app.router.add_post("/events/{id}", calendar_routes.update, name="calendar.update")
    app.router.add_post("/events/{id}/delete", calendar_routes.delete, name="calendar.delete")

    app.router.add_get("/settings", settings.index, name="settings.index")
    app.router.add_post(
        "/settings/personality", settings.set_personality, name="settings.personality"
    )

    return app
