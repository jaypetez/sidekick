"""Login + logout endpoints for the browser-friendly auth flow.

When ``SIDEKICK_WEB_AUTH_TOKEN`` is set, ``auth_middleware`` requires
either an ``Authorization: Bearer`` header (API / CLI) or an
authenticated session cookie (browsers). The session cookie is
established by submitting the correct token to ``POST /login``; the
form renders at ``GET /login``.

The 4 distinct responses:

* ``GET /login`` while authenticated → ``303`` to ``/`` (or ``next``).
* ``GET /login`` while unauthenticated → ``200`` with the form.
* ``POST /login`` with the right token → set session flag, ``303`` to
  the validated ``next`` URL (default ``/``).
* ``POST /login`` with a wrong / missing token → ``401`` with the form
  re-rendered and an error message.

``POST /logout`` clears the session flag and bounces to ``/login``.
"""

from __future__ import annotations

import logging

import aiohttp_jinja2
from aiohttp import web
from aiohttp_session import get_session

from ...ratelimit import RateLimiter
from ..auth import (
    clear_session_authentication,
    constant_time_equals,
    get_auth_token,
    is_session_authenticated,
    mark_session_authenticated,
    safe_next_url,
)
from ..helpers import client_ip

logger = logging.getLogger(__name__)

# Failed logins allowed per client address per window. The token is a
# long random string, so this mostly stops log spam and makes online
# guessing pointless rather than merely slow.
_LOGIN_FAILURES_PER_WINDOW = 10
_LOGIN_WINDOW_SECONDS = 300

_login_limiter: RateLimiter | None = None


def _get_login_limiter() -> RateLimiter:
    global _login_limiter
    if _login_limiter is None:
        _login_limiter = RateLimiter(
            max_requests=_LOGIN_FAILURES_PER_WINDOW,
            window_seconds=_LOGIN_WINDOW_SECONDS,
        )
    return _login_limiter


def reset_login_limiter() -> None:
    """Test hook: forget all failed-login buckets."""
    global _login_limiter
    _login_limiter = None


def _resolve_next(request: web.Request) -> str:
    """Pull a safe ``next`` URL from the query string or the POST form."""
    return safe_next_url(request.query.get("next"))


async def _resolve_next_from_form(request: web.Request) -> str:
    form = await request.post()
    raw = form.get("next")
    return safe_next_url(str(raw) if raw is not None else None)


async def index(request: web.Request) -> web.Response:
    """Render the login form.

    Short-circuits to the dashboard if auth is disabled or the session
    is already authenticated — landing on the form would be confusing
    when there's nothing to log in to.
    """
    expected = get_auth_token()
    next_url = _resolve_next(request)
    if expected is None:
        # Auth not configured — there is no token to enter; just bounce.
        raise web.HTTPSeeOther(location=next_url)

    session = await get_session(request)
    if is_session_authenticated(session):
        raise web.HTTPSeeOther(location=next_url)

    return aiohttp_jinja2.render_template(
        "login.html",
        request,
        {"next_url": next_url, "error": None},
    )


async def submit(request: web.Request) -> web.Response:
    """Validate the submitted token and set the session flag."""
    expected = get_auth_token()
    next_url = await _resolve_next_from_form(request)
    if expected is None:
        # Defensive: if auth was disabled mid-flight, treat as success.
        raise web.HTTPSeeOther(location=next_url)

    form = await request.post()
    raw_candidate = form.get("token")
    candidate = str(raw_candidate).strip() if raw_candidate is not None else ""

    if not candidate or not constant_time_equals(expected, candidate):
        ip = client_ip(request)
        if not await _get_login_limiter().acquire(("login", ip)):
            logger.warning("Login throttled for %s", ip)
            response = aiohttp_jinja2.render_template(
                "login.html",
                request,
                {"next_url": next_url, "error": "Too many attempts. Wait a few minutes."},
            )
            response.set_status(429)
            return response
        logger.warning("Login attempt rejected from %s (next=%s)", ip, next_url)
        response = aiohttp_jinja2.render_template(
            "login.html",
            request,
            {"next_url": next_url, "error": "Invalid token. Try again."},
        )
        response.set_status(401)
        return response

    session = await get_session(request)
    mark_session_authenticated(session)
    raise web.HTTPSeeOther(location=next_url)


async def logout(request: web.Request) -> web.Response:
    """Clear the session and bounce back to the login form."""
    session = await get_session(request)
    clear_session_authentication(session)
    raise web.HTTPSeeOther(location="/login")
