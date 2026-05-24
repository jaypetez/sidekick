"""Settings page — personality + read-only env summary."""

from __future__ import annotations

import os
import re
from typing import Any

import aiohttp_jinja2
from aiohttp import web

from ...agent import PERSONALITY_PRESETS
from ..helpers import run_sync

_DISPLAYABLE_ENV = (
    "TIMEZONE",
    "CLAUDE_MODEL",
    "LLM_PROVIDER",
    "MORNING_REMINDER_TIME",
    "PRE_EVENT_REMINDER_MINUTES",
    "SIDEKICK_WEB_HOST",
    "SIDEKICK_WEB_PORT",
)

# Belt-and-braces: even though _DISPLAYABLE_ENV is an explicit allowlist,
# fail loudly at import time if a maintainer ever adds something that
# looks like a credential. Future env additions must not include any of
# these substrings (case-insensitive).
_SECRET_NAME_PATTERN = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSWORD)")

_offenders = [name for name in _DISPLAYABLE_ENV if _SECRET_NAME_PATTERN.search(name)]
if _offenders:
    raise RuntimeError(
        f"settings.py _DISPLAYABLE_ENV must not include credential-shaped names: {_offenders!r}"
    )


def _agent(bot_data: dict[str, Any]) -> Any:
    agent = bot_data.get("agent")
    if agent is None:
        raise web.HTTPServiceUnavailable(reason="agent not ready")
    return agent


@aiohttp_jinja2.template("settings.html")
async def index(request: web.Request) -> dict[str, Any]:
    agent = _agent(request.app["bot_data"])
    env_summary = {key: os.getenv(key, "") for key in _DISPLAYABLE_ENV}
    return {
        "personality": agent.personality or "",
        "presets": [k for k in PERSONALITY_PRESETS if k != "default"],
        "env": env_summary,
    }


async def set_personality(request: web.Request) -> web.Response:
    agent = _agent(request.app["bot_data"])
    form = await request.post()
    style = str(form.get("style", ""))
    await run_sync(agent.set_personality, style)
    raise web.HTTPSeeOther(location="/settings")
