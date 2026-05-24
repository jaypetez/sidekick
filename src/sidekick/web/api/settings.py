"""Settings JSON endpoints — read + edit runtime config, plus personality."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from ... import runtime_config
from ...services import llm as llm_service
from ...services import settings as settings_service
from .envelope import error, ok

logger = logging.getLogger(__name__)


def _agent_or_none(request: web.Request) -> Any:
    return request.config_dict["bot_data"].get("agent")


async def index(request: web.Request) -> web.Response:
    """Return the current settings — secrets always redacted."""
    agent = _agent_or_none(request)
    personality_info: dict[str, Any] | None = None
    if agent is not None:
        personality_info = settings_service.personality(agent)
    return ok(
        {
            "settings": settings_service.snapshot(redacted=True),
            "editable_keys": sorted(runtime_config.EDITABLE_KEYS),
            "secret_keys": sorted(runtime_config.SECRET_KEYS & runtime_config.EDITABLE_KEYS),
            "personality": personality_info,
        }
    )


async def update(request: web.Request) -> web.Response:
    """Apply a batch of settings changes. Empty string clears the override."""
    body = await request.json()
    if not isinstance(body, dict):
        return error("invalid_body", "expected JSON object", status=400)
    if not body:
        return error("missing_field", "at least one key must be provided", status=400)

    # Coerce all values to str; reject anything weird up-front.
    changes: dict[str, str] = {}
    for key, value in body.items():
        if not isinstance(key, str):
            return error(
                "invalid_key", f"key must be a string, got {type(key).__name__}", status=400
            )
        if value is None:
            changes[key] = ""
        elif isinstance(value, str | int | float | bool):
            changes[key] = str(value)
        else:
            return error("invalid_value", f"unsupported value type for {key}", status=400)

    try:
        result = await settings_service.update(changes, agent=_agent_or_none(request))
    except runtime_config.ConfigError as exc:
        return error("not_editable", str(exc), status=400)
    return ok(
        {
            **result,
            "settings": settings_service.snapshot(redacted=True),
        }
    )


async def test_llm(request: web.Request) -> web.Response:
    agent = _agent_or_none(request)
    if agent is None:
        return error("agent_unavailable", "agent not ready", status=503)
    result = await llm_service.probe(agent)
    if not result.get("ok"):
        return error("probe_failed", str(result.get("error") or "unknown error"), status=502)
    return ok(result)


async def personality_index(request: web.Request) -> web.Response:
    agent = _agent_or_none(request)
    if agent is None:
        return error("agent_unavailable", "agent not ready", status=503)
    return ok(settings_service.personality(agent))


async def personality_update(request: web.Request) -> web.Response:
    agent = _agent_or_none(request)
    if agent is None:
        return error("agent_unavailable", "agent not ready", status=503)
    body = await request.json()
    if not isinstance(body, dict):
        return error("invalid_body", "expected JSON object", status=400)
    style = str(body.get("style", ""))
    label = await settings_service.set_personality(agent, style)
    return ok({"label": label, **settings_service.personality(agent)})
