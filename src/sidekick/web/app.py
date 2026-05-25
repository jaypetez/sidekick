"""aiohttp Application factory for the admin dashboard.

The factory takes a reference to the live ``bot_data`` dict (the same one
PTB exposes on its ``Application``) so handlers can reach the running
scheduler, agent, and MCP session without IPC. A ``run_sync`` helper wraps
synchronous provider calls in ``loop.run_in_executor`` to keep the shared
event loop responsive — the same pattern ``MCPServer._dispatch`` uses.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote as _urlquote

import aiohttp_jinja2
import jinja2
from aiohttp import web
from aiohttp_session import AbstractStorage, session_middleware
from aiohttp_session.cookie_storage import EncryptedCookieStorage

from ..calendar.chronary import ChronaryProvider
from ..storage.sqlite_tasks import SQLiteTaskStore
from . import csrf as csrf_mod
from .auth import get_auth_token, load_or_create_session_secret
from .handlers import (
    calendar_routes,
    chat,
    dashboard,
    health,
    reminders,
    settings,
    tasks,
)
from .handlers import (
    login as login_handler,
)
from .middleware import (
    auth_middleware,
    csrf_middleware,
    security_headers_middleware,
)


@web.middleware
async def _no_cache_html_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Tell browsers not to cache HTML responses.

    The dashboard's state (task counts, reminder list, agent status) changes
    constantly — a cached page is misleading. Static assets under /static/
    are not affected; they can stay cached.
    """
    response = await handler(request)
    content_type = response.headers.get("Content-Type", "")
    if content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


def _urlencode_filter(value: Any) -> str:
    """Percent-encode ``value`` for safe use inside URL path segments."""
    if value is None:
        return ""
    return _urlquote(str(value), safe="")


async def _csrf_context(request: web.Request) -> dict[str, Any]:
    """Expose the current request's CSRF token to every template."""
    from aiohttp_session import get_session

    session = await get_session(request)
    return {
        "csrf_token": csrf_mod.get_or_create_token(session),
        "auth_enabled": get_auth_token() is not None,
    }


async def _csrf_endpoint(request: web.Request) -> web.Response:
    """Return the current session's CSRF token as JSON.

    Used by the test suite (and any future SPA-style client) to fetch a
    token without scraping a rendered page. The endpoint itself is a GET,
    so the CSRF middleware lets it through.
    """
    from aiohttp_session import get_session

    session = await get_session(request)
    token = csrf_mod.get_or_create_token(session)
    return web.json_response({"csrf": token})


def _build_session_storage() -> AbstractStorage:
    """Construct the cookie-backed session storage.

    ``EncryptedCookieStorage`` requires ``cryptography``. If it's not
    available we fall back to ``SimpleCookieStorage`` so the dashboard
    still works in minimal envs (test cookies are not security-sensitive
    because the cookie's only payload is a random CSRF token).
    """
    secret = load_or_create_session_secret()
    try:
        return EncryptedCookieStorage(secret, cookie_name="SIDEKICK_SESSION", httponly=True)
    except Exception:  # pragma: no cover - cryptography missing
        from aiohttp_session import SimpleCookieStorage

        return SimpleCookieStorage(cookie_name="SIDEKICK_SESSION")


def make_app(
    *,
    bot_data: dict[str, Any],
    task_store: SQLiteTaskStore | None = None,
    calendar_provider: ChronaryProvider | None = None,
) -> web.Application:
    """Build a configured aiohttp Application for the dashboard.

    ``bot_data`` is shared by reference with PTB, so updates to scheduler,
    agent, MCP state etc. are visible immediately. ``task_store`` is a
    dedicated SQLite connection for the web layer — multiple readers /
    one writer is fine under WAL.
    """
    storage = _build_session_storage()
    # Middleware order matters: aiohttp runs them top-down on the request
    # path, so an entry later in the list runs *inside* an earlier one. We
    # need ``auth_middleware`` to be able to read the session cookie (to
    # honor a freshly-issued login), so it must sit *after* the session
    # middleware. CSRF stays between session and auth so it can validate
    # the login POST itself using the session-bound token.
    middlewares: list[Any] = [
        security_headers_middleware,
        _no_cache_html_middleware,
        session_middleware(storage),
        csrf_middleware,
        auth_middleware,
    ]
    app = web.Application(middlewares=middlewares)
    app["bot_data"] = bot_data
    app["task_store"] = task_store if task_store is not None else SQLiteTaskStore()
    # Calendar provider is constructed lazily — ChronaryProvider's __init__
    # reads CHRONARY_* env vars and would fail in tests without them. The
    # caller (production: bot.py; tests: fixture) passes one in explicitly.
    app["calendar"] = calendar_provider

    templates_dir = Path(__file__).parent / "templates"
    jinja_env = aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        # autoescape=True is the linchpin of the XSS hardening: every
        # ``{{ value }}`` in the templates is HTML-escaped by default.
        autoescape=jinja2.select_autoescape(
            enabled_extensions=("html", "htm", "xml"),
            default_for_string=True,
        ),
        context_processors=[aiohttp_jinja2.request_processor, _csrf_context],
    )
    # Override Jinja2's default ``urlencode`` (which preserves ``/``) with a
    # stricter variant that escapes every reserved URL character — necessary
    # because we use the filter inside path segments.
    jinja_env.filters["urlencode"] = _urlencode_filter

    static_dir = Path(__file__).parent / "static"
    app.router.add_static("/static/", path=static_dir, name="static")

    app.router.add_get("/", dashboard.home, name="home")
    app.router.add_get("/health", health.health, name="health")
    app.router.add_get("/_csrf", _csrf_endpoint, name="csrf")

    app.router.add_get("/login", login_handler.index, name="login.index")
    app.router.add_post("/login", login_handler.submit, name="login.submit")
    app.router.add_post("/logout", login_handler.logout, name="login.logout")

    app.router.add_get("/chat", chat.index, name="chat.index")
    app.router.add_post("/chat", chat.send, name="chat.send")
    app.router.add_post("/chat/reset", chat.reset, name="chat.reset")

    app.router.add_get("/reminders", reminders.index, name="reminders.index")
    app.router.add_post("/reminders", reminders.create, name="reminders.create")
    app.router.add_post("/reminders/{id}", reminders.update, name="reminders.update")
    app.router.add_post("/reminders/{id}/delete", reminders.delete, name="reminders.delete")

    app.router.add_get("/tasks", tasks.index, name="tasks.index")
    app.router.add_get("/tasks/{list_name}", tasks.detail, name="tasks.detail")
    app.router.add_post("/tasks/{list_name}/items", tasks.add_item, name="tasks.add_item")
    app.router.add_post(
        "/tasks/{list_name}/items/{item_id}/complete",
        tasks.complete_item,
        name="tasks.complete_item",
    )
    app.router.add_post(
        "/tasks/{list_name}/items/{item_id}/delete",
        tasks.delete_item,
        name="tasks.delete_item",
    )
    app.router.add_post(
        "/tasks/{list_name}/clear-completed",
        tasks.clear_completed,
        name="tasks.clear_completed",
    )
    app.router.add_post("/tasks/{list_name}/delete", tasks.delete_list, name="tasks.delete_list")

    app.router.add_get("/events", calendar_routes.index, name="calendar.index")
    app.router.add_post("/events", calendar_routes.create, name="calendar.create")
    app.router.add_post("/events/{id}", calendar_routes.update, name="calendar.update")
    app.router.add_post("/events/{id}/delete", calendar_routes.delete, name="calendar.delete")

    app.router.add_get("/settings", settings.index, name="settings.index")
    app.router.add_post(
        "/settings/personality", settings.set_personality, name="settings.personality"
    )

    return app
