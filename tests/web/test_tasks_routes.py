"""Tests for /tasks routes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from sidekick.web import make_app


@pytest.fixture
def task_store():
    """Mocked SQLiteTaskStore for handler tests."""
    store = MagicMock()
    store.list_task_lists.return_value = [
        {"title": "Costco", "id": "1"},
        {"title": "Home", "id": "2"},
    ]
    store.list_tasks.return_value = [{"id": 7, "title": "milk", "status": "incomplete"}]
    store.add_tasks.return_value = {"status": "added"}
    store.complete_task.return_value = {"status": "completed", "title": "milk"}
    store.delete_task.return_value = {"status": "deleted", "title": "milk"}
    store.complete_item_by_id.return_value = {"status": "completed", "title": "milk", "id": 7}
    store.delete_item_by_id.return_value = {"status": "deleted", "title": "milk", "id": 7}
    store.clear_completed.return_value = {"status": "cleared"}
    store.delete_task_list.return_value = {"status": "deleted"}
    return store


@pytest.fixture
def tasks_app(bot_data, task_store):
    return make_app(bot_data=bot_data, task_store=task_store)


@pytest_asyncio.fixture
async def tasks_client(aiohttp_client, tasks_app):
    from .conftest import CsrfClient

    return CsrfClient(await aiohttp_client(tasks_app))


@pytest.mark.asyncio
async def test_index_lists_task_lists_with_open_counts(tasks_client, task_store):
    resp = await tasks_client.get("/tasks")
    assert resp.status == 200
    body = await resp.text()
    assert "Costco" in body
    assert "Home" in body
    # list_tasks called once per list to count open items
    assert task_store.list_tasks.call_count == 2


@pytest.mark.asyncio
async def test_detail_shows_items(tasks_client, task_store):
    resp = await tasks_client.get("/tasks/Costco")
    assert resp.status == 200
    body = await resp.text()
    assert "milk" in body
    task_store.list_tasks.assert_any_call({"list_name": "Costco"})


@pytest.mark.asyncio
async def test_add_item_posts_to_store(tasks_client, task_store):
    resp = await tasks_client.post(
        "/tasks/Costco/items", data={"title": "eggs"}, allow_redirects=False
    )
    assert resp.status == 303
    assert resp.headers["Location"] == "/tasks/Costco"
    task_store.add_tasks.assert_called_once_with({"list_name": "Costco", "items": ["eggs"]})


@pytest.mark.asyncio
async def test_add_item_rejects_empty_title(tasks_client):
    resp = await tasks_client.post("/tasks/Costco/items", data={"title": ""}, allow_redirects=False)
    assert resp.status == 400


@pytest.mark.asyncio
async def test_complete_item_calls_store(tasks_client, task_store):
    resp = await tasks_client.post("/tasks/Costco/items/7/complete", allow_redirects=False)
    assert resp.status == 303
    task_store.complete_item_by_id.assert_called_once_with(7)


@pytest.mark.asyncio
async def test_complete_item_404s_when_not_found(tasks_client, task_store):
    task_store.complete_item_by_id.return_value = {"error": "No task with id 7"}
    resp = await tasks_client.post("/tasks/Costco/items/7/complete", allow_redirects=False)
    assert resp.status == 404


@pytest.mark.asyncio
async def test_delete_item_calls_store(tasks_client, task_store):
    resp = await tasks_client.post("/tasks/Costco/items/7/delete", allow_redirects=False)
    assert resp.status == 303
    task_store.delete_item_by_id.assert_called_once_with(7)


@pytest.mark.asyncio
async def test_delete_item_404s_when_missing(tasks_client, task_store):
    task_store.delete_item_by_id.return_value = {"error": "No task with id 7"}
    resp = await tasks_client.post("/tasks/Costco/items/7/delete", allow_redirects=False)
    assert resp.status == 404


@pytest.mark.asyncio
async def test_clear_completed_calls_store(tasks_client, task_store):
    resp = await tasks_client.post("/tasks/Costco/clear-completed", allow_redirects=False)
    assert resp.status == 303
    task_store.clear_completed.assert_called_once_with({"list_name": "Costco"})


@pytest.mark.asyncio
async def test_delete_list_calls_store(tasks_client, task_store):
    resp = await tasks_client.post("/tasks/Costco/delete", allow_redirects=False)
    assert resp.status == 303
    assert resp.headers["Location"] == "/tasks"
    task_store.delete_task_list.assert_called_once_with({"list_name": "Costco"})


@pytest.mark.asyncio
async def test_delete_list_404s_when_missing(tasks_client, task_store):
    task_store.delete_task_list.return_value = {"error": "Task list 'X' not found"}
    resp = await tasks_client.post("/tasks/X/delete", allow_redirects=False)
    assert resp.status == 404


@pytest.mark.asyncio
async def test_add_item_502s_when_store_raises(tasks_client, task_store):
    """A SQLite-level failure should surface as 502, not crash to 500."""
    task_store.add_tasks.side_effect = RuntimeError("db locked")
    resp = await tasks_client.post(
        "/tasks/Costco/items", data={"title": "eggs"}, allow_redirects=False
    )
    assert resp.status == 502


@pytest.mark.asyncio
async def test_clear_completed_502s_when_store_raises(tasks_client, task_store):
    task_store.clear_completed.side_effect = RuntimeError("db locked")
    resp = await tasks_client.post("/tasks/Costco/clear-completed", allow_redirects=False)
    assert resp.status == 502
