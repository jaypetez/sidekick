"""Settings page shell + legacy personality POST fallback.

The actual data flow lives in the JS module
``/static/js/pages/settings.js`` which talks to ``/api/settings`` and
``/api/personality``. This handler just serves an empty shell so the
``Settings`` nav link still resolves to a page; the JS populates it.

The legacy ``POST /settings/personality`` route stays so the existing
HTML form keeps working for clients without JS — same business call
the JS path makes, just routed through a 303 redirect instead of a
JSON response.
"""

from __future__ import annotations

from typing import Any

import aiohttp_jinja2
from aiohttp import web

from ..helpers import run_sync


def _agent(bot_data: dict[str, Any]) -> Any:
    agent = bot_data.get("agent")
    if agent is None:
        raise web.HTTPServiceUnavailable(reason="agent not ready")
    return agent


@aiohttp_jinja2.template("settings.html")
async def index(request: web.Request) -> dict[str, Any]:
    # 503 fast if the agent isn't ready — keeps the existing test contract
    # and avoids serving a page that immediately errors on its first fetch.
    _agent(request.app["bot_data"])
    return {}


async def set_personality(request: web.Request) -> web.Response:
    """Legacy no-JS fallback. The JS path uses PATCH /api/personality."""
    agent = _agent(request.app["bot_data"])
    form = await request.post()
    style = str(form.get("style", ""))
    await run_sync(agent.set_personality, style)
    raise web.HTTPSeeOther(location="/settings")
