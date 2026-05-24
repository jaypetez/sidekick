"""Dashboard home page handler."""

from __future__ import annotations

from typing import Any

import aiohttp_jinja2
from aiohttp import web

from ..helpers import run_sync


@aiohttp_jinja2.template("dashboard.html")
async def home(request: web.Request) -> dict[str, Any]:
    """Render the dashboard with health + counts at a glance."""
    bot_data: dict[str, Any] = request.app["bot_data"]
    scheduler = bot_data.get("scheduler")
    agent = bot_data.get("agent")
    mcp_task = bot_data.get("mcp_task")

    scheduler_running = bool(scheduler and getattr(scheduler, "running", False))
    mcp_up = bool(mcp_task and not mcp_task.done())
    tool_count = len(agent.tools) if agent is not None else 0

    reminder_count = 0
    if scheduler is not None:
        jobs = await run_sync(scheduler.get_jobs)
        reminder_count = len(jobs)

    return {
        "scheduler_running": scheduler_running,
        "mcp_up": mcp_up,
        "tool_count": tool_count,
        "reminder_count": reminder_count,
        "personality": agent.personality if agent is not None else "",
    }
