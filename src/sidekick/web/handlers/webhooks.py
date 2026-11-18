"""``POST /webhooks/chronary`` — receive Chronary ``event.reminder`` pushes.

Exempt from session/bearer auth, CSRF and the Host check (see
``web/auth.py::WEBHOOK_PATHS``); authenticity comes from the HMAC
signature, verified here before anything else is trusted. The route
answers 404 unless ``CHRONARY_WEBHOOK_SECRET`` is configured, so it simply
doesn't exist on installs that haven't opted in.

Delivery to Telegram happens in a background task so we can acknowledge
inside Chronary's 10-second window regardless of Telegram latency. The
delivery id is recorded *before* acknowledging, so a Chronary retry of the
same delivery is a no-op even across a restart.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from aiohttp import web
from chronary import SignatureVerificationError

from ... import runtime_config
from ...telegram_format import send_markdown_v2
from ...util import run_sync, watch_task
from ...webhooks import (
    MAX_BODY_BYTES,
    DeliveryLog,
    InvalidPayload,
    ReminderNotice,
    format_reminder,
    parse_reminder,
)

logger = logging.getLogger(__name__)

WEBHOOK_LOG_KEY = "webhook_log"
WEBHOOK_TASKS_KEY = "webhook_tasks"


def _delivery_log(app: web.Application) -> DeliveryLog:
    log = app.get(WEBHOOK_LOG_KEY)
    if log is None:
        log = DeliveryLog()
        app[WEBHOOK_LOG_KEY] = log
    assert isinstance(log, DeliveryLog)
    return log


async def chronary(request: web.Request) -> web.StreamResponse:
    secret = os.getenv("CHRONARY_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise web.HTTPNotFound()

    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        raise web.HTTPRequestEntityTooLarge(
            max_size=MAX_BODY_BYTES, actual_size=request.content_length
        )
    body = await request.content.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY_BYTES, actual_size=len(body))

    try:
        notice = parse_reminder(
            body,
            request.headers,
            secret=secret,
            calendar_id=os.getenv("CHRONARY_CALENDAR_ID") or None,
        )
    except SignatureVerificationError as exc:
        # Never log the body or headers of an unauthenticated request.
        logger.warning("Rejected Chronary webhook from %s: %s", request.remote, exc)
        raise web.HTTPUnauthorized(reason="invalid signature") from exc
    except InvalidPayload as exc:
        logger.warning("Unusable Chronary webhook payload: %s", exc)
        raise web.HTTPBadRequest(reason="invalid payload") from exc

    log = _delivery_log(request.app)
    log.mark_received()
    if notice is None:
        return web.Response(status=204)  # authentic, but not a reminder for us

    if not await run_sync(log.record, notice.delivery_id):
        logger.info("Duplicate Chronary delivery %s ignored", notice.delivery_id)
        return web.json_response({"status": "duplicate"})

    task = watch_task(
        asyncio.create_task(_deliver(request.app["bot_data"], notice)),
        f"webhook-delivery:{notice.delivery_id}",
    )
    tasks: set[asyncio.Task[Any]] = request.app.setdefault(WEBHOOK_TASKS_KEY, set())
    tasks.add(task)  # keep a reference until it finishes
    task.add_done_callback(tasks.discard)
    return web.json_response({"status": "accepted"})


async def _deliver(bot_data: dict[str, Any], notice: ReminderNotice) -> None:
    agent = bot_data.get("agent")
    bot = getattr(agent, "bot", None)
    chat_id = os.getenv("REMINDER_CHAT_ID", "").strip()
    if bot is None or not chat_id:
        logger.warning(
            "Chronary reminder for event %s not delivered: %s",
            notice.event_id,
            "no Telegram bot (web-only mode)" if bot is None else "REMINDER_CHAT_ID unset",
        )
        return
    v2, plain = format_reminder(notice, runtime_config.timezone_name())
    await send_markdown_v2(bot, int(chat_id), v2, plain_text=plain)
    logger.info("Delivered Chronary reminder for event %s", notice.event_id)
