"""System page — read-only view of runtime status and effective configuration.

Server-rendered (no JS) so it works even when the agent or LLM is down,
which is exactly when someone opens it. All data comes from
:mod:`sidekick.services.system`; this module only adapts it to a template.
"""

from __future__ import annotations

from typing import Any

import aiohttp_jinja2
from aiohttp import web

from ...services import system as system_service
from ...util import run_sync
from .webhooks import WEBHOOK_LOG_KEY


@aiohttp_jinja2.template("system.html")
async def index(request: web.Request) -> dict[str, Any]:
    info = await system_service.overview(
        request.app["bot_data"],
        webhook_log=request.app.get(WEBHOOK_LOG_KEY),
    )
    return {
        "info": info,
        "uptime": system_service.format_uptime(info["uptime_seconds"]),
        "groups": await run_sync(system_service.config_report),
    }
