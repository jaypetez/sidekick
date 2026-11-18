"""Health endpoint — JSON status for monitoring + the dashboard tile."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ...util import run_sync
from .envelope import ok


async def health(request: web.Request) -> web.Response:
    bot_data: dict[str, Any] = request.config_dict["bot_data"]
    scheduler = bot_data.get("scheduler")
    agent = bot_data.get("agent")
    mcp_task = bot_data.get("mcp_task")

    reminder_count = 0
    if scheduler is not None:
        jobs = await run_sync(scheduler.get_jobs)
        reminder_count = len(jobs)

    payload = {
        "scheduler": bool(scheduler and getattr(scheduler, "running", False)),
        "mcp": bool(mcp_task and not mcp_task.done()),
        "reminders": reminder_count,
        "tools": len(agent.tools) if agent is not None else 0,
    }
    return ok(payload)
