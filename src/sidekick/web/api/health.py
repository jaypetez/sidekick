"""Health endpoint — JSON status for monitoring + the dashboard tile."""

from __future__ import annotations

from aiohttp import web

from ...services import system as system_service
from ..handlers.webhooks import WEBHOOK_LOG_KEY
from .envelope import ok


async def health(request: web.Request) -> web.Response:
    payload = await system_service.status(
        request.config_dict["bot_data"],
        webhook_log=request.config_dict.get(WEBHOOK_LOG_KEY),
    )
    return ok(payload)
