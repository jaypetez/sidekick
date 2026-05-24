"""Reminder CRUD handlers.

Reuses the helper functions in ``sidekick.reminders`` directly — they
operate on the live scheduler instance from ``bot_data``, so mutations
take effect immediately on the running scheduler.
"""

from __future__ import annotations

from typing import Any

import aiohttp_jinja2
from aiohttp import web

from ...reminders import (
    BUILTIN_IDS,
    add_reminder,
    get_all_reminders,
    remove_reminder,
    update_reminder,
)
from ..helpers import run_sync


def _require(bot_data: dict[str, Any]) -> tuple[Any, Any]:
    scheduler = bot_data.get("scheduler")
    agent = bot_data.get("agent")
    if scheduler is None or agent is None:
        raise web.HTTPServiceUnavailable(reason="bot not ready")
    return scheduler, agent


@aiohttp_jinja2.template("reminders/list.html")
async def index(request: web.Request) -> dict[str, Any]:
    scheduler, _ = _require(request.app["bot_data"])
    reminders = await run_sync(get_all_reminders, scheduler)
    return {"reminders": reminders, "builtin_ids": BUILTIN_IDS}


async def create(request: web.Request) -> web.Response:
    scheduler, agent = _require(request.app["bot_data"])
    form = await request.post()

    message = str(form.get("message", "")).strip()
    if not message:
        raise web.HTTPBadRequest(reason="message is required")
    try:
        hour = int(str(form.get("hour", "")))
        minute = int(str(form.get("minute", "")))
    except ValueError as exc:
        raise web.HTTPBadRequest(reason="hour and minute must be integers") from exc

    day_of_week_raw = str(form.get("day_of_week", "")).strip()
    day_of_week = day_of_week_raw or None
    chat_id_raw = str(form.get("chat_id", "")).strip()
    chat_id = int(chat_id_raw) if chat_id_raw else 0

    await run_sync(
        add_reminder,
        scheduler,
        agent,
        message,
        hour,
        minute,
        chat_id,
        day_of_week,
    )
    raise web.HTTPSeeOther(location="/reminders")


async def update(request: web.Request) -> web.Response:
    scheduler, agent = _require(request.app["bot_data"])
    reminder_id = request.match_info["id"]
    form = await request.post()

    enabled_raw = form.get("enabled")
    enabled: bool | None
    if enabled_raw is None:
        enabled = None
    else:
        enabled = str(enabled_raw).lower() in {"1", "true", "on", "yes"}

    message = str(form.get("message", "")).strip() or None
    hour_raw = str(form.get("hour", "")).strip()
    minute_raw = str(form.get("minute", "")).strip()
    day_raw = str(form.get("day_of_week", "")).strip()

    result = await run_sync(
        update_reminder,
        scheduler,
        agent,
        reminder_id,
        message,
        int(hour_raw) if hour_raw else None,
        int(minute_raw) if minute_raw else None,
        day_raw or None,
        enabled,
    )
    if "error" in result:
        raise web.HTTPBadRequest(reason=result["error"])
    raise web.HTTPSeeOther(location="/reminders")


async def delete(request: web.Request) -> web.Response:
    scheduler, _ = _require(request.app["bot_data"])
    reminder_id = request.match_info["id"]
    if reminder_id in BUILTIN_IDS:
        raise web.HTTPBadRequest(
            reason=f"Built-in reminder '{reminder_id}' cannot be removed; disable it instead."
        )
    result = await run_sync(remove_reminder, scheduler, reminder_id)
    if "error" in result:
        raise web.HTTPNotFound(reason=result["error"])
    raise web.HTTPSeeOther(location="/reminders")
