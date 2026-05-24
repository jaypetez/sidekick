"""Tests for the MarkdownV2 escape helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.constants import ParseMode
from telegram.error import BadRequest

from sidekick.telegram_format import escape_v2, reply_safe, send_safe


def test_escape_v2_escapes_all_special_chars():
    # MarkdownV2 special chars per Telegram spec.
    specials = r"_*[]()~`>#+-=|{}.!"
    escaped = escape_v2(specials)
    for ch in specials:
        assert f"\\{ch}" in escaped


def test_escape_v2_plain_text_unchanged():
    assert escape_v2("hello world") == "hello world"


def test_escape_v2_period_and_dash():
    out = escape_v2("hi. - ok")
    assert "\\." in out
    assert "\\-" in out


@pytest.mark.asyncio
async def test_send_safe_uses_markdown_v2_on_success():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value="msg")
    result = await send_safe(bot, 42, "hello.")
    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["parse_mode"] == ParseMode.MARKDOWN_V2
    assert kwargs["chat_id"] == 42
    assert "\\." in kwargs["text"]
    assert result == "msg"


@pytest.mark.asyncio
async def test_send_safe_falls_back_to_plain_text_on_bad_request():
    bot = MagicMock()
    bot.send_message = AsyncMock(
        side_effect=[BadRequest("can't parse entities"), "plain-msg"]
    )
    result = await send_safe(bot, 7, "tricky [text]")
    assert bot.send_message.await_count == 2
    second_kwargs = bot.send_message.await_args_list[1].kwargs
    # Fallback must be the original unescaped text and must not request MarkdownV2.
    assert second_kwargs["text"] == "tricky [text]"
    assert "parse_mode" not in second_kwargs
    assert result == "plain-msg"


@pytest.mark.asyncio
async def test_reply_safe_uses_markdown_v2_on_success():
    message = MagicMock()
    message.reply_text = AsyncMock(return_value="ok")
    result = await reply_safe(message, "hi!")
    message.reply_text.assert_awaited_once()
    kwargs = message.reply_text.await_args.kwargs
    assert kwargs["parse_mode"] == ParseMode.MARKDOWN_V2
    assert "\\!" in kwargs["text"]
    assert result == "ok"


@pytest.mark.asyncio
async def test_reply_safe_falls_back_on_bad_request():
    message = MagicMock()
    message.reply_text = AsyncMock(
        side_effect=[BadRequest("entity"), "plain-reply"]
    )
    result = await reply_safe(message, "raw _text_")
    assert message.reply_text.await_count == 2
    second_kwargs = message.reply_text.await_args_list[1].kwargs
    assert second_kwargs["text"] == "raw _text_"
    assert "parse_mode" not in second_kwargs
    assert result == "plain-reply"
