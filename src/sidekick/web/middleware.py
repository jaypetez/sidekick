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
from urllib.parse import quote as _urlquote

from aiohttp import web
from aiohttp_session import get_session

from . import csrf
from .auth import (
    constant_time_equals,
    extract_bearer,
    get_auth_token,
    is_login_path,
    is_public_path,
    is_session_authenticated,
)

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
    """Enforce auth when ``SIDEKICK_WEB_AUTH_TOKEN`` is set.

    Three ways a request can be authenticated:

    1. The path is in :data:`~.auth.PUBLIC_PATH_PREFIXES` or
       :data:`~.auth.LOGIN_PATHS` (always allowed).
    2. The session cookie carries the "authenticated" marker (set by the
       login form). This is the browser path.
    3. The request carries ``Authorization: Bearer <token>``. This keeps
       API clients, CLI scripts, and the test suite working unchanged.

    For unauthenticated browser GETs (``Accept: text/html`` and no
    ``Authorization`` header) we issue a 303 redirect to
    ``/login?next=<original>`` so the user lands on a real form instead
    of a useless 401 page. Everything else (API clients, bad-Bearer
    requests) still gets the standard 401 + ``WWW-Authenticate``
    contract.
    """
    expected = get_auth_token()
    if expected is None or is_public_path(request.path) or is_login_path(request.path):
        return await handler(request)

    session = await get_session(request)
    if is_session_authenticated(session):
        return await handler(request)

    auth_header = request.headers.get("Authorization")
    candidate = extract_bearer(auth_header)
    if candidate and constant_time_equals(expected, candidate):
        return await handler(request)

    accepts_html = "text/html" in request.headers.get("Accept", "")
    if request.method == "GET" and accepts_html and auth_header is None:
        target = request.path_qs or "/"
        location = f"/login?next={_urlquote(target, safe='')}"
        raise web.HTTPSeeOther(location=location)

    raise web.HTTPUnauthorized(
        reason="Authentication required",
        headers={"WWW-Authenticate": 'Bearer realm="sidekick"'},
    )
