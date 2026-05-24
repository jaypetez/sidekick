"""Allowlist + rate-limit checks for the Telegram handle_message path."""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token-not-real")

from sidekick import bot as bot_module  # noqa: E402
from sidekick import ratelimit  # noqa: E402


def _make_update(*, user_id: int = 7, chat_id: int = 42, text: str = "hi") -> MagicMock:
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_chat = SimpleNamespace(id=chat_id)
    update.effective_user = SimpleNamespace(id=user_id, username="alice")
    return update


def _make_context(agent: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {"agent": agent}
    ctx.bot.send_chat_action = AsyncMock()
    return ctx


@pytest.fixture(autouse=True)
def _reset_limiter():
    ratelimit.reset_default_limiter()
    yield
    ratelimit.reset_default_limiter()


@pytest.mark.asyncio
async def test_denied_user_does_not_invoke_agent(monkeypatch, caplog):
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    agent = MagicMock()
    agent.process_message = AsyncMock(return_value="hello")
    update = _make_update(user_id=999)
    context = _make_context(agent)

    with caplog.at_level(logging.WARNING, logger="sidekick.bot"):
        await bot_module.handle_message(update, context)

    agent.process_message.assert_not_awaited()
    update.message.reply_text.assert_awaited_once()
    body = update.message.reply_text.await_args.args[0]
    assert "allowlist" in body.lower()
    # Structured log line should mention user_id and chat_id.
    record_text = " ".join(rec.getMessage() for rec in caplog.records)
    assert "user_id=999" in record_text
    assert "chat_id=42" in record_text


@pytest.mark.asyncio
async def test_allowed_user_calls_agent(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "7,8")
    agent = MagicMock()
    agent.process_message = AsyncMock(return_value="hi back")
    update = _make_update(user_id=7)
    context = _make_context(agent)

    # Patch reply_safe so we don't go through telegram_format's markdown path.
    sent: list[str] = []

    async def fake_reply_safe(message, text, **kwargs):
        sent.append(text)
        return MagicMock()

    monkeypatch.setattr(bot_module, "reply_safe", fake_reply_safe)

    await bot_module.handle_message(update, context)

    agent.process_message.assert_awaited_once_with(42, "hi")
    assert sent == ["hi back"]


@pytest.mark.asyncio
async def test_handle_start_denies_unlisted_user(monkeypatch, caplog):
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    update = _make_update(user_id=1234)
    context = _make_context(MagicMock())

    with caplog.at_level(logging.WARNING, logger="sidekick.bot"):
        await bot_module.handle_start(update, context)

    body = update.message.reply_text.await_args.args[0]
    assert "allowlist" in body.lower()
    record_text = " ".join(rec.getMessage() for rec in caplog.records)
    assert "user_id=1234" in record_text


@pytest.mark.asyncio
async def test_rate_limited_user_skips_agent(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "7")
    monkeypatch.setenv("SIDEKICK_RATE_LIMIT_MAX", "2")
    monkeypatch.setenv("SIDEKICK_RATE_LIMIT_WINDOW_SECONDS", "60")
    ratelimit.reset_default_limiter()

    agent = MagicMock()
    agent.process_message = AsyncMock(return_value="ok")

    async def fake_reply_safe(message, text, **kwargs):
        return MagicMock()

    monkeypatch.setattr(bot_module, "reply_safe", fake_reply_safe)

    for _ in range(2):
        update = _make_update(user_id=7)
        context = _make_context(agent)
        await bot_module.handle_message(update, context)

    # Third request must be rejected before reaching the agent.
    update = _make_update(user_id=7)
    context = _make_context(agent)
    await bot_module.handle_message(update, context)

    assert agent.process_message.await_count == 2
    body = update.message.reply_text.await_args.args[0]
    assert "too quickly" in body.lower()
