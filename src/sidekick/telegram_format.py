"""Telegram MarkdownV2 helpers.

Telegram's MarkdownV2 requires escaping a specific set of characters
even outside formatting runs. The LLM produces free-form text that
routinely contains unescaped ``.``, ``-``, ``(`` etc., which makes
``parse_mode=MarkdownV2`` reject the whole message with ``BadRequest:
can't parse entities``.

Strategy: flat-escape every outbound message and try MarkdownV2. If
Telegram still rejects it (rare — usually unmatched code fences from
the LLM), retry as plain text. The user always sees *something*.

Refining the escape to leave legitimate fenced code blocks intact is a
wishlist follow-up.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.helpers import escape_markdown

if TYPE_CHECKING:
    from telegram import Bot, Message

logger = logging.getLogger(__name__)


def escape_v2(text: str) -> str:
    """Escape ``text`` for Telegram MarkdownV2.

    Thin wrapper around :func:`telegram.helpers.escape_markdown` pinned
    to version 2 so callers don't have to remember the kwarg.
    """
    return escape_markdown(text, version=2)


async def send_safe(bot: "Bot", chat_id: int, text: str, **kwargs: Any) -> "Message":
    """Send ``text`` as MarkdownV2 with a plain-text fallback.

    Returns the resulting :class:`telegram.Message`. ``kwargs`` are
    forwarded to :meth:`Bot.send_message` (e.g. ``disable_notification``).
    """
    escaped = escape_v2(text)
    try:
        return await bot.send_message(
            chat_id=chat_id, text=escaped, parse_mode=ParseMode.MARKDOWN_V2, **kwargs
        )
    except BadRequest:
        logger.warning("Telegram rejected MarkdownV2 message; resending as plain text")
        return await bot.send_message(chat_id=chat_id, text=text, **kwargs)


async def reply_safe(message: "Message", text: str, **kwargs: Any) -> "Message":
    """Reply to ``message`` using MarkdownV2, falling back to plain text."""
    escaped = escape_v2(text)
    try:
        return await message.reply_text(
            text=escaped, parse_mode=ParseMode.MARKDOWN_V2, **kwargs
        )
    except BadRequest:
        logger.warning("Telegram rejected MarkdownV2 reply; resending as plain text")
        return await message.reply_text(text=text, **kwargs)
