"""Health endpoint — JSON status for monitoring + the dashboard tile."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ... import runtime_config
from ...util import run_sync
from ...webhooks import load_webhook_secret
from ..handlers.webhooks import WEBHOOK_LOG_KEY
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

    webhook_log = request.config_dict.get(WEBHOOK_LOG_KEY)
    last_received = getattr(webhook_log, "last_received_at", None)
    payload = {
        "scheduler": bool(scheduler and getattr(scheduler, "running", False)),
        "mcp": bool(mcp_task and not mcp_task.done()),
        "reminders": reminder_count,
        "tools": len(agent.tools) if agent is not None else 0,
        # A webhook-mode install that never hears from Chronary (tunnel down,
        # endpoint deactivated) would otherwise fail silently.
        "webhook": {
            "configured": load_webhook_secret() is not None,
            "pre_event_source": runtime_config.pre_event_source(),
            "last_received_at": last_received.isoformat() if last_received else None,
        },
    }
    return ok(payload)
