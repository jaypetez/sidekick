"""Health endpoint — JSON status for monitoring + the dashboard tile."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ..helpers import run_sync


async def health(request: web.Request) -> web.Response:
    """Return JSON with scheduler + MCP liveness and basic counts."""
    bot_data: dict[str, Any] = request.app["bot_data"]
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
    return web.json_response(payload)
