"""Calendar JSON endpoints."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from ...services import calendar as calendar_service
from .envelope import error, ok

logger = logging.getLogger(__name__)


def _provider(request: web.Request) -> Any:
    provider = request.config_dict.get("calendar")
    if provider is None:
        raise web.HTTPServiceUnavailable(reason="calendar provider not ready")
    return provider


async def index(request: web.Request) -> web.Response:
    provider = _provider(request)
    try:
        days = int(request.query.get("days", "14"))
    except ValueError:
        days = 14
    try:
        events = await calendar_service.list_events(provider, days=days)
    except Exception as exc:
        logger.exception("list_events failed")
        return error("provider_error", str(exc), status=502)
    return ok({"events": events, "days": max(1, min(days, 90))})


async def create(request: web.Request) -> web.Response:
    provider = _provider(request)
    body = await request.json()
    if not isinstance(body, dict):
        return error("invalid_body", "expected JSON object", status=400)
    required = ("summary", "start_datetime", "end_datetime")
    missing = [k for k in required if not str(body.get(k, "")).strip()]
    if missing:
        return error("missing_field", f"required: {', '.join(missing)}", status=400)
    try:
        result = await calendar_service.create_event(
            provider,
            summary=str(body["summary"]).strip(),
            start_datetime=str(body["start_datetime"]).strip(),
            end_datetime=str(body["end_datetime"]).strip(),
            description=(str(body.get("description") or "").strip() or None),
            location=(str(body.get("location") or "").strip() or None),
        )
    except Exception as exc:
        logger.exception("create_event failed")
        return error("provider_error", str(exc), status=502)
    return ok(result, status=201)


async def update(request: web.Request) -> web.Response:
    provider = _provider(request)
    event_id = request.match_info["id"]
    body = await request.json()
    if not isinstance(body, dict):
        return error("invalid_body", "expected JSON object", status=400)
    fields = {k: str(v).strip() for k, v in body.items() if v}
    if not fields:
        return error("missing_field", "at least one field must be provided", status=400)
    try:
        result = await calendar_service.update_event(provider, event_id, **fields)
    except Exception as exc:
        logger.exception("update_event failed for %s", event_id)
        return error("provider_error", str(exc), status=502)
    return ok(result)


async def delete(request: web.Request) -> web.Response:
    provider = _provider(request)
    event_id = request.match_info["id"]
    try:
        result = await calendar_service.delete_event(provider, event_id)
    except Exception as exc:
        logger.exception("delete_event failed for %s", event_id)
        return error("provider_error", str(exc), status=502)
    return ok(result)
