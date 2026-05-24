"""The reminder chat-id sentinel must be a non-int that process_message accepts."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from sidekick.agent import SidekickAgent
from sidekick.reminders import _REMINDER_CHAT_ID


def test_reminder_sentinel_is_not_an_int():
    """A non-int sentinel cannot collide with any Telegram chat id."""
    assert not isinstance(_REMINDER_CHAT_ID, int)
    assert isinstance(_REMINDER_CHAT_ID, str)
    assert _REMINDER_CHAT_ID  # non-empty


@pytest.mark.asyncio
async def test_process_message_accepts_sentinel():
    """process_message must accept the sentinel as chat_id without TypeError."""
    llm = MagicMock()
    response = MagicMock(stop_reason="end_turn")
    text_block = MagicMock()
    text_block.text = "ack"
    response.content = [text_block]
    llm.chat = AsyncMock(return_value=response)

    agent = SidekickAgent(mcp_session=MagicMock(), llm=llm)
    reply = await agent.process_message(_REMINDER_CHAT_ID, "ping")
    assert reply == "ack"
    # Confirms the dict key path also handles str keys
    assert _REMINDER_CHAT_ID in agent.conversation_history

    agent.clear_history(_REMINDER_CHAT_ID)
    assert _REMINDER_CHAT_ID not in agent.conversation_history
