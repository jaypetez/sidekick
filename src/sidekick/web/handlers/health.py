"""Health endpoint — JSON status for monitoring + the dashboard tile.

Unauthenticated callers always see the minimal ``{"status": "ok"}``
payload so load balancers and uptime probes don't leak operational
state. Callers presenting a valid ``Authorization: Bearer`` token (when
``SIDEKICK_WEB_AUTH_TOKEN`` is configured) — or any caller when auth is
disabled — get the full health report including scheduler / MCP / tool
counts.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ..auth import constant_time_equals, extract_bearer, get_auth_token
from ..helpers import run_sync


def _is_authenticated(request: web.Request) -> bool:
    """True if either auth is disabled or the request carries a valid token."""
    expected = get_auth_token()
    if expected is None:
        return True
    candidate = extract_bearer(request.headers.get("Authorization"))
    if candidate is None:
        return False
    return constant_time_equals(expected, candidate)


async def health(request: web.Request) -> web.Response:
    """Return JSON health.

    Unauth callers: ``{"status": "ok"}`` — enough to satisfy liveness
    probes without leaking which subsystems are up. Authed callers (or
    any caller in token-less mode): full breakdown.
    """
    if not _is_authenticated(request):
        return web.json_response({"status": "ok"})

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
