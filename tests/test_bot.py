"""Tests for the bot.py Telegram entry-point handlers.

These don't open a real bot connection — they construct synthetic Update objects
with mocked .message / .effective_chat / .reply_text and assert that handlers
do the right routing, calling `agent.clear_history`, `agent.set_personality`,
`agent.process_message`, etc.
"""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# bot.py reads env at import; provide a dummy token so import succeeds even when
# the host env doesn't set one.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token-not-real")

from sidekick import bot as bot_module  # noqa: E402


def _make_update(
    *,
    message_text: str | None = "hi",
    chat_id: int = 42,
    has_message: bool = True,
    has_chat: bool = True,
) -> MagicMock:
    """Build a minimal Update-shaped mock for handler tests."""
    update = MagicMock()
    if has_message:
        update.message = MagicMock()
        update.message.text = message_text
        update.message.reply_text = AsyncMock()
    else:
        update.message = None
    if has_chat:
        update.effective_chat = SimpleNamespace(id=chat_id)
    else:
        update.effective_chat = None
    return update


def _make_context(agent: MagicMock, args: list[str] | None = None) -> MagicMock:
    """Build a minimal Context-shaped mock."""
    context = MagicMock()
    context.bot_data = {"agent": agent}
    context.args = args
    context.bot.send_chat_action = AsyncMock()
    return context


@pytest.mark.asyncio
async def test_handle_start_sends_intro():
    update = _make_update()
    context = _make_context(MagicMock())
    await bot_module.handle_start(update, context)
    update.message.reply_text.assert_awaited_once()
    body = update.message.reply_text.await_args.args[0]
    assert "Sidekick" in body
    assert "/reset" in body


@pytest.mark.asyncio
async def test_handle_reset_clears_history_and_replies():
    update = _make_update()
    agent = MagicMock()
    context = _make_context(agent)
    await bot_module.handle_reset(update, context)
    agent.clear_history.assert_called_once_with(42)
    update.message.reply_text.assert_awaited_once_with("Conversation history cleared!")


@pytest.mark.asyncio
async def test_handle_get_id_reports_chat_id():
    update = _make_update(chat_id=-100999)
    context = _make_context(MagicMock())
    await bot_module.handle_get_id(update, context)
    update.message.reply_text.assert_awaited_once()
    body = update.message.reply_text.await_args.args[0]
    assert "-100999" in body


@pytest.mark.asyncio
async def test_handle_personality_no_args_shows_current_and_presets():
    update = _make_update()
    agent = MagicMock()
    agent.personality = ""
    context = _make_context(agent, args=[])
    await bot_module.handle_personality(update, context)
    body = update.message.reply_text.await_args.args[0]
    assert "Current personality" in body
    assert "snarky" in body  # preset list
    agent.set_personality.assert_not_called()


@pytest.mark.asyncio
async def test_handle_personality_with_args_sets_and_confirms():
    update = _make_update()
    agent = MagicMock()
    agent.set_personality.return_value = "pirate"
    context = _make_context(agent, args=["pirate"])
    await bot_module.handle_personality(update, context)
    agent.set_personality.assert_called_once_with("pirate")
    update.message.reply_text.assert_awaited_once_with("Personality set to: pirate")


@pytest.mark.asyncio
async def test_handle_message_routes_to_agent():
    update = _make_update(message_text="what's tomorrow?")
    agent = MagicMock()
    agent.process_message = AsyncMock(return_value="You have 2 things.")
    context = _make_context(agent)
    await bot_module.handle_message(update, context)
    agent.process_message.assert_awaited_once_with(42, "what's tomorrow?")
    update.message.reply_text.assert_awaited_once()
    body = update.message.reply_text.await_args.args[0]
    assert "2 things" in body


@pytest.mark.asyncio
async def test_handle_message_skips_when_no_text():
    update = _make_update(message_text=None)
    agent = MagicMock()
    agent.process_message = AsyncMock()
    context = _make_context(agent)
    await bot_module.handle_message(update, context)
    agent.process_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_message_replies_apology_on_agent_failure():
    update = _make_update(message_text="oops")
    agent = MagicMock()
    agent.process_message = AsyncMock(side_effect=RuntimeError("boom"))
    context = _make_context(agent)
    await bot_module.handle_message(update, context)
    body = update.message.reply_text.await_args.args[0]
    assert "something went wrong" in body.lower()


def test_main_raises_without_telegram_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        bot_module.main()


def test_main_builds_application_and_starts_polling(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    fake_app = MagicMock()
    fake_builder = MagicMock()
    fake_builder.token.return_value = fake_builder
    fake_builder.post_init.return_value = fake_builder
    fake_builder.post_shutdown.return_value = fake_builder
    fake_builder.build.return_value = fake_app

    with patch("sidekick.bot.Application") as application_cls:
        application_cls.builder.return_value = fake_builder
        bot_module.main()

    fake_builder.token.assert_called_once_with("test-token-not-real")
    fake_app.add_handler.assert_called()  # CommandHandler + MessageHandler entries
    fake_app.run_polling.assert_called_once_with(drop_pending_updates=True)


@pytest.mark.asyncio
async def test_post_shutdown_stops_scheduler_and_signals_mcp(monkeypatch):
    application = MagicMock()
    scheduler = MagicMock()
    scheduler.running = True
    shutdown_event = MagicMock()
    mcp_task = MagicMock()
    mcp_task.done.return_value = False
    application.bot_data = {
        "scheduler": scheduler,
        "shutdown_event": shutdown_event,
        "mcp_task": mcp_task,
        "slack_platform": None,
    }

    # Patch asyncio.wait_for so it returns immediately.
    async def _fake_wait_for(awaitable, timeout):
        return None

    monkeypatch.setattr("sidekick.bot.asyncio.wait_for", _fake_wait_for)

    await bot_module.post_shutdown(application)

    scheduler.shutdown.assert_called_once_with(wait=False)
    shutdown_event.set.assert_called_once()
