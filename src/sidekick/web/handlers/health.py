"""Health endpoint — JSON status for monitoring + the dashboard tile.

Unauthenticated callers always see the minimal ``{"status": "ok"}``
payload so load balancers and uptime probes don't leak operational
state. Callers presenting a valid ``Authorization: Bearer`` token (when
``SIDEKICK_WEB_AUTH_TOKEN`` is configured) — or any caller when auth is
disabled — get the full health report including scheduler / MCP / tool
counts.
"""

from __future__ import annotations

from aiohttp import web

from ...services import system as system_service
from ..auth import constant_time_equals, extract_bearer, get_auth_token


def _is_authenticated(request: web.Request) -> bool:
    """True if either auth is disabled or the request carries a valid token."""
    expected = get_auth_token()
    if expected is None:
        return True
    candidate = extract_bearer(request.headers.get("Authorization"))
    if candidate is None:
        return False
    return constant_time_equals(expected, candidate)


async def health(request: web.Request) -> web.Response:
    """Return JSON health.

    Unauth callers: ``{"status": "ok"}`` — enough to satisfy liveness
    probes without leaking which subsystems are up. Authed callers (or
    any caller in token-less mode): full breakdown.
    """
    if not _is_authenticated(request):
        return web.json_response({"status": "ok"})

    # Long-standing flat shape; the webhook detail lives on /api/health.
    payload = await system_service.status(request.app["bot_data"], include_webhook=False)
    return web.json_response(payload)
