"""Tests for /api/chat endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_history_returns_pairs(client, bot_data):
    bot_data["agent"].conversation_history = {
        "web:local": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [SimpleNamespace(type="text", text="hello")]},
        ]
    }
    resp = await client.get("/api/chat")
    assert resp.status == 200
    payload = await resp.json()
    assert payload["data"]["chat_id"] == "web:local"
    assert payload["data"]["messages"] == [{"user": "hi", "assistant": "hello"}]


@pytest.mark.asyncio
async def test_send_requires_text(client):
    resp = await client.post("/api/chat", json={})
    assert resp.status == 400
    payload = await resp.json()
    assert payload["error"]["code"] == "missing_field"


@pytest.mark.asyncio
async def test_send_returns_assistant_reply(client, bot_data):
    bot_data["agent"].process_message = AsyncMock(return_value="hi back")
    resp = await client.post("/api/chat", json={"text": "hi"})
    assert resp.status == 200
    payload = await resp.json()
    assert payload["data"]["assistant"] == "hi back"
    assert payload["data"]["user"] == "hi"


@pytest.mark.asyncio
async def test_send_uses_custom_chat_id_when_provided(client, bot_data):
    bot_data["agent"].process_message = AsyncMock(return_value="ok")
    await client.post("/api/chat", json={"text": "hi", "chat_id": "cli:user-1"})
    args = bot_data["agent"].process_message.call_args.args
    assert args[0] == "cli:user-1"


@pytest.mark.asyncio
async def test_reset_calls_clear_history(client, bot_data):
    resp = await client.post("/api/chat/reset")
    assert resp.status == 200
    bot_data["agent"].clear_history.assert_called_with("web:local")


@pytest.mark.asyncio
async def test_send_wraps_agent_error_in_envelope(client, bot_data):
    bot_data["agent"].process_message = AsyncMock(side_effect=RuntimeError("upstream down"))
    resp = await client.post("/api/chat", json={"text": "hi"})
    assert resp.status == 502
    payload = await resp.json()
    assert payload["error"]["code"] == "agent_error"
    assert "upstream down" in payload["error"]["message"]
