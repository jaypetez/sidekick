"""System JSON endpoints — deployment overview and the configuration report."""

from __future__ import annotations

from aiohttp import web

from ...services import system as system_service
from ...util import run_sync
from ..handlers.webhooks import WEBHOOK_LOG_KEY
from .envelope import ok


async def overview(request: web.Request) -> web.Response:
    """``GET /api/system`` — version, uptime, status, LLM, platforms, paths."""
    data = await system_service.overview(
        request.config_dict["bot_data"],
        webhook_log=request.config_dict.get(WEBHOOK_LOG_KEY),
    )
    return ok(data)


async def config(request: web.Request) -> web.Response:
    """``GET /api/config`` — every known setting, grouped, secrets redacted."""
    return ok({"groups": await run_sync(system_service.config_report)})
