"""Task list JSON endpoints."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from ...services import tasks as tasks_service
from .envelope import error, ok

logger = logging.getLogger(__name__)


def _store(request: web.Request) -> Any:
    store = request.config_dict.get("task_store")
    if store is None:
        raise web.HTTPServiceUnavailable(reason="task store not ready")
    return store


async def index(request: web.Request) -> web.Response:
    lists = await tasks_service.list_lists(_store(request))
    return ok({"lists": lists})


async def detail(request: web.Request) -> web.Response:
    list_name = request.match_info["list_name"]
    items = await tasks_service.get_list(_store(request), list_name)
    return ok({"name": list_name, "items": items})


async def add_item(request: web.Request) -> web.Response:
    list_name = request.match_info["list_name"]
    body = await request.json()
    titles_raw = body.get("titles") if isinstance(body, dict) else None
    if not titles_raw and isinstance(body, dict) and "title" in body:
        titles_raw = [body["title"]]
    if not isinstance(titles_raw, list) or not titles_raw:
        return error("invalid_body", "expected 'titles' (list) or 'title' (string)", status=400)
    titles = [str(t).strip() for t in titles_raw if str(t).strip()]
    if not titles:
        return error("empty_titles", "titles cannot be blank", status=400)
    try:
        await tasks_service.add_items(_store(request), list_name, titles)
    except Exception as exc:
        logger.exception("add_items failed for list %s", list_name)
        return error("store_error", str(exc), status=502)
    return ok({"added": titles}, status=201)


async def complete_item(request: web.Request) -> web.Response:
    list_name = request.match_info["list_name"]
    title = request.match_info["title"]
    result = await tasks_service.complete(_store(request), list_name, title)
    if "error" in result:
        return error("not_found", result["error"], status=404)
    return ok(result)


async def delete_item(request: web.Request) -> web.Response:
    list_name = request.match_info["list_name"]
    title = request.match_info["title"]
    result = await tasks_service.delete_item(_store(request), list_name, title)
    if "error" in result:
        return error("not_found", result["error"], status=404)
    return ok(result)


async def clear_completed(request: web.Request) -> web.Response:
    list_name = request.match_info["list_name"]
    try:
        await tasks_service.clear_completed(_store(request), list_name)
    except Exception as exc:
        logger.exception("clear_completed failed for list %s", list_name)
        return error("store_error", str(exc), status=502)
    return ok({"list_name": list_name})


async def delete_list(request: web.Request) -> web.Response:
    list_name = request.match_info["list_name"]
    result = await tasks_service.delete_list(_store(request), list_name)
    if "error" in result:
        return error("not_found", result["error"], status=404)
    return ok(result)
