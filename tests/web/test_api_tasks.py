"""Tests for /api/tasks endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from sidekick.web import make_app

from .conftest import CsrfClient


@pytest.fixture
def task_store():
    store = MagicMock()
    store.list_task_lists.return_value = [{"title": "Costco"}, {"title": "Home"}]
    store.list_tasks.return_value = [{"title": "milk", "status": "incomplete"}]
    store.add_tasks.return_value = {"status": "added"}
    store.complete_task.return_value = {"status": "completed", "title": "milk"}
    store.delete_task.return_value = {"status": "deleted", "title": "milk"}
    store.clear_completed.return_value = {"status": "cleared"}
    store.delete_task_list.return_value = {"status": "deleted"}
    return store


@pytest_asyncio.fixture
async def tasks_client(aiohttp_client, bot_data, task_store):
    inner = await aiohttp_client(make_app(bot_data=bot_data, task_store=task_store))
    return CsrfClient(inner)


@pytest.mark.asyncio
async def test_list_returns_open_counts(tasks_client):
    resp = await tasks_client.get("/api/tasks")
    assert resp.status == 200
    payload = await resp.json()
    lists = payload["data"]["lists"]
    assert {entry["name"] for entry in lists} == {"Costco", "Home"}
    assert all(entry["open_count"] == 1 for entry in lists)


@pytest.mark.asyncio
async def test_detail_returns_items(tasks_client, task_store):
    resp = await tasks_client.get("/api/tasks/Costco")
    assert resp.status == 200
    payload = await resp.json()
    assert payload["data"]["name"] == "Costco"
    assert payload["data"]["items"] == [{"title": "milk", "status": "incomplete"}]
    task_store.list_tasks.assert_any_call({"list_name": "Costco"})


@pytest.mark.asyncio
async def test_add_item_accepts_single_title(tasks_client, task_store):
    resp = await tasks_client.post("/api/tasks/Costco/items", json={"title": "eggs"})
    assert resp.status == 201
    payload = await resp.json()
    assert payload["data"]["added"] == ["eggs"]
    task_store.add_tasks.assert_called_with({"list_name": "Costco", "items": ["eggs"]})


@pytest.mark.asyncio
async def test_add_item_accepts_titles_list(tasks_client, task_store):
    resp = await tasks_client.post("/api/tasks/Costco/items", json={"titles": ["eggs", "bread"]})
    assert resp.status == 201
    task_store.add_tasks.assert_called_with({"list_name": "Costco", "items": ["eggs", "bread"]})


@pytest.mark.asyncio
async def test_add_item_rejects_empty_body(tasks_client):
    resp = await tasks_client.post("/api/tasks/Costco/items", json={})
    assert resp.status == 400
    payload = await resp.json()
    assert payload["error"]["code"] == "invalid_body"


@pytest.mark.asyncio
async def test_complete_item_routes_to_store(tasks_client, task_store):
    resp = await tasks_client.post("/api/tasks/Costco/items/milk/complete")
    assert resp.status == 200
    task_store.complete_task.assert_called_with({"list_name": "Costco", "task_title": "milk"})


@pytest.mark.asyncio
async def test_complete_missing_item_404(tasks_client, task_store):
    task_store.complete_task.return_value = {"error": "not found"}
    resp = await tasks_client.post("/api/tasks/Costco/items/nope/complete")
    assert resp.status == 404
    payload = await resp.json()
    assert payload["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_delete_item_uses_DELETE_verb(tasks_client, task_store):
    resp = await tasks_client.delete("/api/tasks/Costco/items/milk")
    assert resp.status == 200
    task_store.delete_task.assert_called_with({"list_name": "Costco", "task_title": "milk"})


@pytest.mark.asyncio
async def test_clear_completed(tasks_client, task_store):
    resp = await tasks_client.post("/api/tasks/Costco/clear-completed")
    assert resp.status == 200
    task_store.clear_completed.assert_called_once_with({"list_name": "Costco"})


@pytest.mark.asyncio
async def test_delete_list(tasks_client, task_store):
    resp = await tasks_client.delete("/api/tasks/Costco")
    assert resp.status == 200
    task_store.delete_task_list.assert_called_once_with({"list_name": "Costco"})
