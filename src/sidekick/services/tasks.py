"""Task list service functions.

Thin async wrappers around :class:`SQLiteTaskStore`. Sync store calls
are routed through ``run_sync`` so the shared event loop stays
responsive — same pattern the MCP dispatcher uses.
"""

from __future__ import annotations

from typing import Any

from ..util import run_sync


async def list_lists(store: Any) -> list[dict[str, Any]]:
    """Return one entry per list with its open-item count."""
    lists = await run_sync(store.list_task_lists, {})
    out: list[dict[str, Any]] = []
    for entry in lists:
        items = await run_sync(store.list_tasks, {"list_name": entry["title"]})
        out.append({"name": entry["title"], "open_count": len(items)})
    return out


async def get_list(store: Any, list_name: str) -> list[dict[str, Any]]:
    """Return all items in ``list_name`` (the store applies its own status filter)."""
    items = await run_sync(store.list_tasks, {"list_name": list_name})
    return list(items)


async def add_items(store: Any, list_name: str, titles: list[str]) -> None:
    await run_sync(store.add_tasks, {"list_name": list_name, "items": titles})


async def complete(store: Any, list_name: str, title: str) -> dict[str, Any]:
    result = await run_sync(store.complete_task, {"list_name": list_name, "task_title": title})
    return dict(result)


async def delete_item(store: Any, list_name: str, title: str) -> dict[str, Any]:
    result = await run_sync(store.delete_task, {"list_name": list_name, "task_title": title})
    return dict(result)


async def clear_completed(store: Any, list_name: str) -> None:
    await run_sync(store.clear_completed, {"list_name": list_name})


async def delete_list(store: Any, list_name: str) -> dict[str, Any]:
    result = await run_sync(store.delete_task_list, {"list_name": list_name})
    return dict(result)
