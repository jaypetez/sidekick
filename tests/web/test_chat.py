"""Tests for /chat handler — web UI conversation surface."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from sidekick.web import make_app
from sidekick.web.handlers.chat import CHAT_ID, _history_pairs

from .conftest import CsrfClient


@pytest.fixture
def chat_app(bot_data):
    # bot_data fixture from conftest already populates an agent; replace
    # process_message with an AsyncMock so we can assert on calls.
    bot_data["agent"].process_message = AsyncMock(return_value="Hello there.")
    bot_data["agent"].conversation_history = {}
    bot_data["agent"].clear_history = MagicMock(
        side_effect=lambda cid: bot_data["agent"].conversation_history.pop(cid, None)
    )
    return make_app(bot_data=bot_data)


@pytest_asyncio.fixture
async def chat_client(aiohttp_client, chat_app):
    return CsrfClient(await aiohttp_client(chat_app))


@pytest.mark.asyncio
async def test_index_renders_empty_state(chat_client):
    resp = await chat_client.get("/chat")
    assert resp.status == 200
    body = await resp.text()
    assert "Chat" in body
    assert "No messages yet" in body


@pytest.mark.asyncio
async def test_index_503_without_agent(aiohttp_client):
    app = make_app(bot_data={})
    c = await aiohttp_client(app)
    resp = await c.get("/chat")
    assert resp.status == 503


@pytest.mark.asyncio
async def test_send_routes_to_agent_and_redirects(chat_client, bot_data):
    resp = await chat_client.post("/chat", data={"message": "hi"}, allow_redirects=False)
    assert resp.status == 303
    assert resp.headers["Location"] == "/chat"
    bot_data["agent"].process_message.assert_awaited_once_with(CHAT_ID, "hi")


@pytest.mark.asyncio
async def test_send_empty_message_redirects_without_calling_agent(chat_client, bot_data):
    resp = await chat_client.post("/chat", data={"message": "   "}, allow_redirects=False)
    assert resp.status == 303
    bot_data["agent"].process_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_htmx_returns_partial(chat_client, bot_data):
    resp = await chat_client.post(
        "/chat",
        data={"message": "what tomorrow"},
        headers={"HX-Request": "true"},
        allow_redirects=False,
    )
    assert resp.status == 200
    body = await resp.text()
    assert "what tomorrow" in body
    assert "Hello there." in body
    assert "chat-bubble" in body


@pytest.mark.asyncio
async def test_send_swallows_agent_error(chat_client, bot_data):
    bot_data["agent"].process_message = AsyncMock(side_effect=RuntimeError("boom"))
    resp = await chat_client.post(
        "/chat",
        data={"message": "hi"},
        headers={"HX-Request": "true"},
        allow_redirects=False,
    )
    assert resp.status == 200
    body = await resp.text()
    assert "Sorry" in body


@pytest.mark.asyncio
async def test_reset_clears_history(chat_client, bot_data):
    bot_data["agent"].conversation_history[CHAT_ID] = [{"role": "user", "content": "prior"}]
    resp = await chat_client.post("/chat/reset", allow_redirects=False)
    assert resp.status == 303
    assert CHAT_ID not in bot_data["agent"].conversation_history


def test_history_pairs_collapses_user_and_assistant_text():
    agent = SimpleNamespace(
        conversation_history={
            CHAT_ID: [
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "content": [SimpleNamespace(type="text", text="Hello!")],
                },
                {"role": "user", "content": "next"},
                {
                    "role": "assistant",
                    "content": [SimpleNamespace(type="text", text="Sure.")],
                },
            ]
        }
    )
    pairs = _history_pairs(agent)
    assert pairs == [
        {"user": "hi", "assistant": "Hello!"},
        {"user": "next", "assistant": "Sure."},
    ]


def test_history_pairs_skips_tool_only_turns():
    """Tool_use / tool_result-only turns must not appear in the UI history."""
    agent = SimpleNamespace(
        conversation_history={
            CHAT_ID: [
                {"role": "user", "content": "list groceries"},
                {
                    "role": "assistant",
                    "content": [
                        SimpleNamespace(type="tool_use", id="t1", name="list_tasks", input={}),
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "[]"},
                    ],
                },
                {
                    "role": "assistant",
                    "content": [SimpleNamespace(type="text", text="Nothing on it.")],
                },
            ]
        }
    )
    pairs = _history_pairs(agent)
    assert pairs == [{"user": "list groceries", "assistant": "Nothing on it."}]


def test_history_pairs_handles_dict_content_blocks():
    """Some history records use dict-shaped blocks instead of SimpleNamespace."""
    agent = SimpleNamespace(
        conversation_history={
            CHAT_ID: [
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hey."}],
                },
            ]
        }
    )
    pairs = _history_pairs(agent)
    assert pairs == [{"user": "hi", "assistant": "Hey."}]
