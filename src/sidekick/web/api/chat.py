"""Chat JSON endpoints."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from ...services import chat as chat_service
from .envelope import error, ok

logger = logging.getLogger(__name__)


def _agent(request: web.Request) -> Any:
    agent = request.config_dict["bot_data"].get("agent")
    if agent is None:
        raise web.HTTPServiceUnavailable(reason="agent not ready")
    return agent


async def history(request: web.Request) -> web.Response:
    agent = _agent(request)
    chat_id = request.query.get("chat_id") or chat_service.DEFAULT_CHAT_ID
    pairs = chat_service.history_pairs(agent, chat_id=chat_id)
    return ok({"chat_id": chat_id, "messages": pairs})


async def send(request: web.Request) -> web.Response:
    agent = _agent(request)
    body = await request.json()
    if not isinstance(body, dict):
        return error("invalid_body", "expected JSON object", status=400)
    text = str(body.get("text", "")).strip()
    if not text:
        return error("missing_field", "text is required", status=400)
    chat_id = str(body.get("chat_id") or chat_service.DEFAULT_CHAT_ID)
    try:
        reply = await chat_service.send(agent, text, chat_id=chat_id)
    except Exception as exc:
        logger.exception("agent send failed")
        return error("agent_error", str(exc), status=502)
    return ok({"chat_id": chat_id, "user": text, "assistant": reply})


async def reset(request: web.Request) -> web.Response:
    agent = _agent(request)
    chat_id = chat_service.DEFAULT_CHAT_ID
    if request.can_read_body:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = None
        if isinstance(body, dict) and body.get("chat_id"):
            chat_id = str(body["chat_id"])
    await chat_service.reset(agent, chat_id=chat_id)
    return ok({"chat_id": chat_id, "reset": True})
