"""Calendar CRUD handlers.

Wraps ``ChronaryProvider`` calls in ``run_sync``. The provider is passed
in via ``app["calendar"]`` so tests can inject a mock without needing
the real Chronary env vars.

Module is named ``calendar_routes`` because ``calendar`` would shadow
the stdlib ``calendar`` module.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import aiohttp_jinja2
from aiohttp import web

from ..helpers import run_sync

logger = logging.getLogger(__name__)


def _provider(request: web.Request) -> Any:
    provider = request.app.get("calendar")
    if provider is None:
        raise web.HTTPServiceUnavailable(reason="calendar provider not ready")
    return provider


@aiohttp_jinja2.template("calendar/list.html")
async def index(request: web.Request) -> dict[str, Any]:
    """Show upcoming events. Default window: next 14 days."""
    provider = _provider(request)
    try:
        days = int(request.query.get("days", "14"))
    except ValueError:
        days = 14
    days = max(1, min(days, 90))

    start = date.today()
    end = start + timedelta(days=days)
    try:
        events = await run_sync(
            provider.list_events,
            {"start_date": start.isoformat(), "end_date": end.isoformat(), "max_results": 50},
        )
    except Exception as exc:
        logger.exception("list_events failed")
        return {"events": [], "days": days, "error": str(exc)}
    return {"events": events, "days": days, "error": None}


async def create(request: web.Request) -> web.Response:
    provider = _provider(request)
    form = await request.post()
    summary = str(form.get("summary", "")).strip()
    start_dt = str(form.get("start_datetime", "")).strip()
    end_dt = str(form.get("end_datetime", "")).strip()
    if not summary or not start_dt or not end_dt:
        raise web.HTTPBadRequest(reason="summary, start_datetime, end_datetime are required")

    args: dict[str, Any] = {
        "summary": summary,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
    }
    description = str(form.get("description", "")).strip()
    location = str(form.get("location", "")).strip()
    if description:
        args["description"] = description
    if location:
        args["location"] = location

    try:
        await run_sync(provider.create_event, args)
    except Exception as exc:
        logger.exception("create_event failed")
        raise web.HTTPBadGateway(reason=f"calendar provider error: {exc}") from exc
    raise web.HTTPSeeOther(location="/events")


async def update(request: web.Request) -> web.Response:
    provider = _provider(request)
    event_id = request.match_info["id"]
    form = await request.post()

    args: dict[str, Any] = {"event_id": event_id}
    for key in ("summary", "description", "location", "start_datetime", "end_datetime"):
        value = str(form.get(key, "")).strip()
        if value:
            args[key] = value

    if len(args) == 1:  # only event_id — nothing to update
        raise web.HTTPBadRequest(reason="at least one field must be provided")

    try:
        await run_sync(provider.update_event, args)
    except Exception as exc:
        logger.exception("update_event failed for id %s", event_id)
        raise web.HTTPBadGateway(reason=f"calendar provider error: {exc}") from exc
    raise web.HTTPSeeOther(location="/events")


async def delete(request: web.Request) -> web.Response:
    provider = _provider(request)
    event_id = request.match_info["id"]
    try:
        await run_sync(provider.delete_event, {"event_id": event_id})
    except Exception as exc:
        logger.exception("delete_event failed for id %s", event_id)
        raise web.HTTPBadGateway(reason=f"calendar provider error: {exc}") from exc
    raise web.HTTPSeeOther(location="/events")
