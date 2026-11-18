"""Dashboard home page handler."""

from __future__ import annotations

from typing import Any

import aiohttp_jinja2
from aiohttp import web

from ...services import system as system_service
from .webhooks import WEBHOOK_LOG_KEY


@aiohttp_jinja2.template("dashboard.html")
async def home(request: web.Request) -> dict[str, Any]:
    """Render the dashboard with health + counts at a glance."""
    bot_data: dict[str, Any] = request.app["bot_data"]
    info = await system_service.overview(bot_data, webhook_log=request.app.get(WEBHOOK_LOG_KEY))
    agent = bot_data.get("agent")
    return {
        "info": info,
        "uptime": system_service.format_uptime(info["uptime_seconds"]),
        "scheduler_running": info["status"]["scheduler"],
        "mcp_up": info["status"]["mcp"],
        "tool_count": info["status"]["tools"],
        "reminder_count": info["status"]["reminders"],
        "personality": agent.personality if agent is not None else "",
    }
