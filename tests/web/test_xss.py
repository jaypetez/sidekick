"""Verify Jinja2 autoescape protects user-supplied content."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from sidekick.web import make_app

from .conftest import CsrfClient

XSS_PAYLOAD = "<script>alert(1)</script><img src=x onerror=1>"


@pytest_asyncio.fixture
async def xss_client(aiohttp_client, bot_data):
    bot_data["agent"].process_message = AsyncMock(return_value=XSS_PAYLOAD)
    bot_data["agent"].conversation_history = {}

    store = MagicMock()
    store.list_task_lists.return_value = [{"title": XSS_PAYLOAD, "id": "1"}]
    store.list_tasks.return_value = [{"id": 1, "title": XSS_PAYLOAD, "status": "incomplete"}]
    store.add_tasks.return_value = {"status": "added"}

    app = make_app(bot_data=bot_data, task_store=store)
    return CsrfClient(await aiohttp_client(app))


@pytest.mark.asyncio
async def test_chat_response_is_escaped(xss_client):
    """The htmx partial must HTML-escape the agent's reply."""
    resp = await xss_client.post(
        "/chat",
        data={"message": XSS_PAYLOAD},
        headers={"HX-Request": "true"},
        allow_redirects=False,
    )
    assert resp.status == 200
    body = await resp.text()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    assert "&lt;img" in body


@pytest.mark.asyncio
async def test_task_list_title_is_escaped(xss_client):
    """A malicious list name must render as text, not active markup."""
    resp = await xss_client.get("/tasks")
    assert resp.status == 200
    body = await resp.text()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


@pytest.mark.asyncio
async def test_task_item_title_is_escaped(xss_client):
    resp = await xss_client.get("/tasks/Costco")
    assert resp.status == 200
    body = await resp.text()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
