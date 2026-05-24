"""aiohttp middlewares for the dashboard's defense-in-depth layer.

* :func:`security_headers_middleware` — sets CSP, X-Frame-Options,
  Referrer-Policy, X-Content-Type-Options, Permissions-Policy on every
  response.
* :func:`csrf_middleware` — verifies the CSRF token on every
  state-changing request. Reads the token from the form field
  ``_csrf`` or the ``X-CSRF-Token`` header. Skips ``/static/`` and
  ``/health`` so monitoring stays trivial.
* :func:`auth_middleware` — when ``SIDEKICK_WEB_AUTH_TOKEN`` is set,
  requires ``Authorization: Bearer <token>`` on every request except
  ``/static/`` and ``/health``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from aiohttp import web
from aiohttp_session import get_session

from . import csrf
from .auth import extract_bearer, get_auth_token, is_public_path

logger = logging.getLogger(__name__)

# Methods we treat as state-changing and therefore require CSRF for.
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# Locked-down CSP: htmx is loaded from unpkg.com with SRI, everything
# else is same-origin. ``script-src`` includes ``'unsafe-inline'`` only
# because chat.html and reminders.html ship small inline bootstraps that
# would otherwise break. We pin those scripts via SRI in a future PR.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://unpkg.com 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


@web.middleware
async def security_headers_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Add standard browser-security headers to every response."""
    response = await handler(request)
    headers = response.headers
    headers.setdefault("Content-Security-Policy", _CSP)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "no-referrer")
    headers.setdefault("Permissions-Policy", "()")
    return response


async def _extract_csrf_candidate(request: web.Request) -> str | None:
    """Return the CSRF token candidate from the request, or None."""
    header = request.headers.get(csrf.HEADER_NAME)
    if header:
        return header.strip() or None
    ctype = request.headers.get("Content-Type", "")
    if ctype.startswith("application/x-www-form-urlencoded") or ctype.startswith(
        "multipart/form-data"
    ):
        form = await request.post()
        value = form.get(csrf.FORM_FIELD)
        if isinstance(value, str):
            return value.strip() or None
    return None


@web.middleware
async def csrf_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Reject state-changing requests that don't echo a valid CSRF token."""
    if request.method in STATE_CHANGING_METHODS and not is_public_path(request.path):
        session = await get_session(request)
        candidate = await _extract_csrf_candidate(request)
        if not csrf.validate_token(session, candidate):
            logger.warning("CSRF token missing or invalid for %s %s", request.method, request.path)
            raise web.HTTPForbidden(reason="CSRF token missing or invalid")
    return await handler(request)


@web.middleware
async def auth_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Enforce bearer-token auth when ``SIDEKICK_WEB_AUTH_TOKEN`` is set.

    ``/static/`` and ``/health`` are always reachable; ``/health`` itself
    decides what to return for unauthenticated callers.
    """
    expected = get_auth_token()
    if expected is None or is_public_path(request.path):
        return await handler(request)
    candidate = extract_bearer(request.headers.get("Authorization"))
    from .auth import constant_time_equals

    if not candidate or not constant_time_equals(expected, candidate):
        raise web.HTTPUnauthorized(
            reason="Authentication required",
            headers={"WWW-Authenticate": 'Bearer realm="sidekick"'},
        )
    return await handler(request)
