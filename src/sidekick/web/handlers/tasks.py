"""Task list CRUD handlers.

Wraps ``SQLiteTaskStore`` calls in ``run_sync`` so the synchronous
stdlib sqlite3 driver doesn't block the shared event loop. The store
opens its own connection to the SQLite file — under WAL, concurrent
reads with one writer (the MCP subprocess) work fine.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import aiohttp_jinja2
from aiohttp import web

from ..helpers import run_sync

logger = logging.getLogger(__name__)


def _store(request: web.Request) -> Any:
    store = request.app.get("task_store")
    if store is None:
        raise web.HTTPServiceUnavailable(reason="task store not ready")
    return store


@aiohttp_jinja2.template("tasks/list.html")
async def index(request: web.Request) -> dict[str, Any]:
    """Show every task list with the count of incomplete items."""
    store = _store(request)
    lists = await run_sync(store.list_task_lists, {})
    summaries: list[dict[str, Any]] = []
    for entry in lists:
        items = await run_sync(store.list_tasks, {"list_name": entry["title"]})
        summaries.append({"name": entry["title"], "open_count": len(items)})
    return {"lists": summaries}


@aiohttp_jinja2.template("tasks/detail.html")
async def detail(request: web.Request) -> dict[str, Any]:
    store = _store(request)
    list_name = request.match_info["list_name"]
    items = await run_sync(store.list_tasks, {"list_name": list_name})
    return {"list_name": list_name, "items": items}


async def add_item(request: web.Request) -> web.Response:
    store = _store(request)
    list_name = request.match_info["list_name"]
    form = await request.post()
    title = str(form.get("title", "")).strip()
    if not title:
        raise web.HTTPBadRequest(reason="title is required")
    try:
        await run_sync(store.add_tasks, {"list_name": list_name, "items": [title]})
    except Exception as exc:
        logger.exception("add_tasks failed for list %s", list_name)
        raise web.HTTPBadGateway(reason=f"task store error: {exc}") from exc
    raise web.HTTPSeeOther(location=f"/tasks/{quote(list_name, safe='')}")


async def complete_item(request: web.Request) -> web.Response:
    store = _store(request)
    list_name = request.match_info["list_name"]
    try:
        item_id = int(request.match_info["item_id"])
    except ValueError as exc:
        raise web.HTTPBadRequest(reason="item id must be an integer") from exc
    result = await run_sync(store.complete_item_by_id, item_id)
    if "error" in result:
        raise web.HTTPNotFound(reason=result["error"])
    raise web.HTTPSeeOther(location=f"/tasks/{quote(list_name, safe='')}")


async def delete_item(request: web.Request) -> web.Response:
    store = _store(request)
    list_name = request.match_info["list_name"]
    try:
        item_id = int(request.match_info["item_id"])
    except ValueError as exc:
        raise web.HTTPBadRequest(reason="item id must be an integer") from exc
    result = await run_sync(store.delete_item_by_id, item_id)
    if "error" in result:
        raise web.HTTPNotFound(reason=result["error"])
    raise web.HTTPSeeOther(location=f"/tasks/{quote(list_name, safe='')}")


async def clear_completed(request: web.Request) -> web.Response:
    store = _store(request)
    list_name = request.match_info["list_name"]
    try:
        await run_sync(store.clear_completed, {"list_name": list_name})
    except Exception as exc:
        logger.exception("clear_completed failed for list %s", list_name)
        raise web.HTTPBadGateway(reason=f"task store error: {exc}") from exc
    raise web.HTTPSeeOther(location=f"/tasks/{quote(list_name, safe='')}")


async def delete_list(request: web.Request) -> web.Response:
    store = _store(request)
    list_name = request.match_info["list_name"]
    result = await run_sync(store.delete_task_list, {"list_name": list_name})
    if "error" in result:
        raise web.HTTPNotFound(reason=result["error"])
    raise web.HTTPSeeOther(location="/tasks")
