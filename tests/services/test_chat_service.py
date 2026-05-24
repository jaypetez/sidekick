"""Tests for the chat service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from sidekick.services import chat as chat_service


@pytest.mark.asyncio
async def test_send_returns_agent_reply():
    agent = MagicMock()
    agent.process_message = AsyncMock(return_value="hello back")
    reply = await chat_service.send(agent, "hi")
    assert reply == "hello back"
    agent.process_message.assert_awaited_once_with(chat_service.DEFAULT_CHAT_ID, "hi")


@pytest.mark.asyncio
async def test_reset_clears_history():
    agent = MagicMock()
    await chat_service.reset(agent)
    agent.clear_history.assert_called_once_with(chat_service.DEFAULT_CHAT_ID)


def test_history_pairs_collapses_text_only_log():
    agent = MagicMock()
    agent.conversation_history = {
        chat_service.DEFAULT_CHAT_ID: [
            {"role": "user", "content": "ping"},
            {"role": "assistant", "content": [SimpleNamespace(type="text", text="pong")]},
        ]
    }
    pairs = chat_service.history_pairs(agent)
    assert pairs == [{"user": "ping", "assistant": "pong"}]


def test_history_pairs_skips_tool_result_user_messages():
    agent = MagicMock()
    agent.conversation_history = {
        chat_service.DEFAULT_CHAT_ID: [
            {"role": "user", "content": "list events"},
            {"role": "assistant", "content": [SimpleNamespace(type="text", text="checking")]},
            {"role": "user", "content": [{"type": "tool_result", "content": "[]"}]},
            {"role": "assistant", "content": [SimpleNamespace(type="text", text="none today")]},
        ]
    }
    pairs = chat_service.history_pairs(agent)
    # The tool_result user message shouldn't restart the user side of the pair.
    assert {"assistant": "none today"}.items() <= pairs[-1].items()
