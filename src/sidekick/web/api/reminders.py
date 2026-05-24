"""Reminder JSON endpoints."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from ...services import reminders as reminders_service
from .envelope import error, ok

logger = logging.getLogger(__name__)


def _require(request: web.Request) -> tuple[Any, Any]:
    bot_data = request.config_dict["bot_data"]
    scheduler = bot_data.get("scheduler")
    agent = bot_data.get("agent")
    if scheduler is None or agent is None:
        raise web.HTTPServiceUnavailable(reason="bot not ready")
    return scheduler, agent


async def index(request: web.Request) -> web.Response:
    scheduler, _ = _require(request)
    items = await reminders_service.list_all(scheduler)
    return ok({"reminders": items, "builtin_ids": sorted(reminders_service.BUILTIN_IDS)})


async def create(request: web.Request) -> web.Response:
    scheduler, agent = _require(request)
    body = await request.json()
    if not isinstance(body, dict):
        return error("invalid_body", "expected JSON object", status=400)

    message = str(body.get("message", "")).strip()
    if not message:
        return error("missing_field", "message is required", status=400)
    try:
        hour = int(body["hour"])
        minute = int(body["minute"])
    except (KeyError, TypeError, ValueError):
        return error("invalid_field", "hour and minute must be integers", status=400)
    day_of_week = body.get("day_of_week") or None
    chat_id = int(body.get("chat_id") or 0)

    try:
        result = await reminders_service.create(
            scheduler,
            agent,
            message=message,
            hour=hour,
            minute=minute,
            chat_id=chat_id,
            day_of_week=day_of_week,
        )
    except Exception as exc:
        logger.exception("reminder create failed")
        return error("scheduler_error", str(exc), status=502)
    return ok(result, status=201)


async def update(request: web.Request) -> web.Response:
    scheduler, agent = _require(request)
    reminder_id = request.match_info["id"]
    body = await request.json() if request.can_read_body else {}
    if not isinstance(body, dict):
        return error("invalid_body", "expected JSON object", status=400)

    message = body.get("message")
    hour = body.get("hour")
    minute = body.get("minute")
    day = body.get("day_of_week")
    enabled = body.get("enabled")

    try:
        result = await reminders_service.update(
            scheduler,
            agent,
            reminder_id,
            message=str(message).strip() if message else None,
            hour=int(hour) if hour is not None else None,
            minute=int(minute) if minute is not None else None,
            day_of_week=str(day) if day else None,
            enabled=bool(enabled) if enabled is not None else None,
        )
    except (TypeError, ValueError) as exc:
        return error("invalid_field", str(exc), status=400)

    if "error" in result:
        return error("not_found", result["error"], status=404)
    return ok(result)


async def delete(request: web.Request) -> web.Response:
    scheduler, _ = _require(request)
    reminder_id = request.match_info["id"]
    result = await reminders_service.delete(scheduler, reminder_id)
    if "error" in result:
        code = "builtin" if reminder_id in reminders_service.BUILTIN_IDS else "not_found"
        status = 400 if code == "builtin" else 404
        return error(code, result["error"], status=status)
    return ok(result)
