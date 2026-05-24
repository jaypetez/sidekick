"""Verify task title URL-encoding + id-based round-trip delete."""

from __future__ import annotations

from urllib.parse import quote

import pytest
import pytest_asyncio

from sidekick.storage.sqlite_tasks import SQLiteTaskStore
from sidekick.web import make_app

from .conftest import CsrfClient

WEIRD_TITLE = "weird/title?with#chars and 你好"


@pytest_asyncio.fixture
async def real_client(aiohttp_client, bot_data):
    import sqlite3

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = SQLiteTaskStore(conn=conn)
    app = make_app(bot_data=bot_data, task_store=store)
    client = CsrfClient(await aiohttp_client(app))
    return client, store


@pytest.mark.asyncio
async def test_task_title_is_percent_encoded_in_links(real_client):
    """The list & detail pages link to weird-titled lists via percent-encoding."""
    client, store = real_client
    store.add_tasks({"list_name": WEIRD_TITLE, "items": [WEIRD_TITLE]})

    resp = await client.get("/tasks")
    body = await resp.text()
    encoded = quote(WEIRD_TITLE, safe="")
    assert f"/tasks/{encoded}" in body


@pytest.mark.asyncio
async def test_id_based_delete_round_trip(real_client):
    """Even with a weird title, the id-based delete handler removes the row."""
    client, store = real_client
    store.add_tasks({"list_name": "Costco", "items": ["alpha", "beta"]})
    items = store.list_tasks({"list_name": "Costco"})
    alpha_id = next(i["id"] for i in items if i["title"] == "alpha")

    resp = await client.post(f"/tasks/Costco/items/{alpha_id}/delete", allow_redirects=False)
    assert resp.status == 303
    remaining = [i["title"] for i in store.list_tasks({"list_name": "Costco"})]
    assert remaining == ["beta"]


@pytest.mark.asyncio
async def test_id_based_complete_round_trip(real_client):
    client, store = real_client
    store.add_tasks({"list_name": "Costco", "items": ["alpha"]})
    items = store.list_tasks({"list_name": "Costco"})
    item_id = items[0]["id"]

    resp = await client.post(f"/tasks/Costco/items/{item_id}/complete", allow_redirects=False)
    assert resp.status == 303
    # Completed items drop out of list_tasks (which only returns incomplete).
    assert store.list_tasks({"list_name": "Costco"}) == []
