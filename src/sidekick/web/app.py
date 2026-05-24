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

from .handlers import dashboard, health, reminders


def make_app(*, bot_data: dict[str, Any]) -> web.Application:
    """Build a configured aiohttp Application for the dashboard.

    ``bot_data`` is shared by reference with PTB, so updates to scheduler,
    agent, MCP state etc. are visible immediately.
    """
    app = web.Application()
    app["bot_data"] = bot_data

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

    return app
