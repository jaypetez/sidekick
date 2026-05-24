"""``/api/*`` sub-application factory.

A separate sub-app keeps the JSON envelope middleware scoped to JSON
routes only — the HTML side still uses the simpler ``HTTPException``-as-
status-page pattern from aiohttp.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from aiohttp import web

from . import calendar as calendar_routes
from . import chat as chat_routes
from . import health as health_routes
from . import reminders as reminders_routes
from . import settings as settings_routes
from . import tasks as tasks_routes
from .envelope import error

logger = logging.getLogger(__name__)


@web.middleware
async def _envelope_errors(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Catch exceptions and emit a uniform ``{data, error}`` JSON body."""
    try:
        return await handler(request)
    except web.HTTPException as exc:
        # 2xx/3xx redirects flow through unchanged; only error responses get rewrapped.
        if exc.status < 400:
            raise
        code_map = {
            400: "bad_request",
            404: "not_found",
            405: "method_not_allowed",
            415: "unsupported_media_type",
            500: "internal_error",
            502: "bad_gateway",
            503: "service_unavailable",
        }
        return error(
            code_map.get(exc.status, f"http_{exc.status}"),
            exc.reason or exc.__class__.__name__,
            status=exc.status,
        )
    except json.JSONDecodeError as exc:
        return error("invalid_json", str(exc), status=400)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled error in /api handler")
        return error("internal_error", str(exc), status=500)


def make_api_app() -> web.Application:
    """Build the ``/api`` sub-application.

    Mounted with :meth:`aiohttp.web.Application.add_subapp` so it shares
    the parent app's ``["bot_data"]``, ``["task_store"]`` and
    ``["calendar"]`` keys (sub-apps inherit parent state by reference
    when registered before the parent starts).
    """
    api = web.Application(middlewares=[_envelope_errors])

    api.router.add_get("/health", health_routes.health, name="api.health")

    api.router.add_get("/tasks", tasks_routes.index, name="api.tasks.index")
    api.router.add_get("/tasks/{list_name}", tasks_routes.detail, name="api.tasks.detail")
    api.router.add_post(
        "/tasks/{list_name}/items", tasks_routes.add_item, name="api.tasks.add_item"
    )
    api.router.add_post(
        "/tasks/{list_name}/items/{title}/complete",
        tasks_routes.complete_item,
        name="api.tasks.complete_item",
    )
    api.router.add_delete(
        "/tasks/{list_name}/items/{title}",
        tasks_routes.delete_item,
        name="api.tasks.delete_item",
    )
    api.router.add_post(
        "/tasks/{list_name}/clear-completed",
        tasks_routes.clear_completed,
        name="api.tasks.clear_completed",
    )
    api.router.add_delete(
        "/tasks/{list_name}", tasks_routes.delete_list, name="api.tasks.delete_list"
    )

    api.router.add_get("/reminders", reminders_routes.index, name="api.reminders.index")
    api.router.add_post("/reminders", reminders_routes.create, name="api.reminders.create")
    api.router.add_patch("/reminders/{id}", reminders_routes.update, name="api.reminders.update")
    api.router.add_delete("/reminders/{id}", reminders_routes.delete, name="api.reminders.delete")

    api.router.add_get("/events", calendar_routes.index, name="api.events.index")
    api.router.add_post("/events", calendar_routes.create, name="api.events.create")
    api.router.add_patch("/events/{id}", calendar_routes.update, name="api.events.update")
    api.router.add_delete("/events/{id}", calendar_routes.delete, name="api.events.delete")

    api.router.add_get("/chat", chat_routes.history, name="api.chat.history")
    api.router.add_post("/chat", chat_routes.send, name="api.chat.send")
    api.router.add_post("/chat/reset", chat_routes.reset, name="api.chat.reset")

    api.router.add_get("/settings", settings_routes.index, name="api.settings.index")
    api.router.add_patch("/settings", settings_routes.update, name="api.settings.update")
    api.router.add_post(
        "/settings/test-llm", settings_routes.test_llm, name="api.settings.test_llm"
    )
    api.router.add_get(
        "/personality", settings_routes.personality_index, name="api.personality.index"
    )
    api.router.add_patch(
        "/personality", settings_routes.personality_update, name="api.personality.update"
    )

    return api
