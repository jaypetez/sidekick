"""Slack adapter.

Concrete `ChatPlatform` using slack-bolt in async + socket mode.
Lives alongside the existing Telegram bot — bot.py launches both
concurrently when SLACK_BOT_TOKEN is set.

Setup (Slack side):
  1. Create a Slack app at https://api.slack.com/apps
  2. Enable Socket Mode → generate an `xapp-…` app-level token
  3. Add Bot Token Scopes: chat:write, app_mentions:read,
     im:history, im:read, im:write
  4. Install to workspace → grab the `xoxb-…` bot user token
  5. Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env

Chat IDs use the prefix "sl:" (so per-chat history and reminder
targets don't collide with Telegram's "tg:" ids).
"""

import asyncio
import logging
import os
from typing import Awaitable, Callable

from .base import ChatPlatform, CommandHandler, DefaultHandler, IncomingMessage

logger = logging.getLogger(__name__)

CHAT_ID_PREFIX = "sl"


class SlackPlatform(ChatPlatform):
    name = "slack"

    def __init__(
        self,
        *,
        bot_token: str | None = None,
        app_token: str | None = None,
    ) -> None:
        self._bot_token = bot_token or os.environ["SLACK_BOT_TOKEN"]
        self._app_token = app_token or os.environ["SLACK_APP_TOKEN"]
        self._commands: dict[str, CommandHandler] = {}
        self._default_handler: DefaultHandler | None = None
        self._app = None
        self._socket_handler = None
        self._app_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # ChatPlatform interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        # Imported lazily so the dependency is only required when Slack
        # is actually enabled.
        from slack_bolt.app.async_app import AsyncApp
        from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler

        self._app = AsyncApp(token=self._bot_token)
        self._register_listeners(self._app)
        self._socket_handler = AsyncSocketModeHandler(self._app, self._app_token)
        # start_async() returns a coroutine that runs forever — run as a task
        self._app_task = asyncio.create_task(self._socket_handler.start_async())
        logger.info("Slack platform started (socket mode)")

    async def stop(self) -> None:
        if self._socket_handler is not None:
            await self._socket_handler.close_async()
        if self._app_task is not None and not self._app_task.done():
            self._app_task.cancel()
        logger.info("Slack platform stopped")

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        markdown: bool = True,
    ) -> None:
        channel = _strip_prefix(chat_id)
        if self._app is None:
            raise RuntimeError("SlackPlatform.send_message called before start()")
        await self._app.client.chat_postMessage(
            channel=channel,
            text=text,
            mrkdwn=markdown,
        )

    def register_command(self, name: str, handler: CommandHandler) -> None:
        self._commands[name] = handler

    def register_default_handler(self, handler: DefaultHandler) -> None:
        self._default_handler = handler

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _register_listeners(self, app) -> None:
        @app.event("message")
        async def _on_message(event, say):
            # Ignore bot's own messages and channel join/leave events.
            if event.get("subtype") is not None:
                return
            if event.get("bot_id"):
                return

            text = event.get("text", "").strip()
            channel = event.get("channel", "")
            user = event.get("user", "")
            chat_id = f"{CHAT_ID_PREFIX}:{channel}"

            # Command handling: messages starting with `/`
            if text.startswith("/"):
                parts = text.split(None, 1)
                cmd_name = parts[0].lstrip("/").lower()
                args = parts[1].split() if len(parts) > 1 else []
                handler = self._commands.get(cmd_name)
                if handler:
                    msg = IncomingMessage(
                        chat_id=chat_id, sender_id=user, text=text, platform=self.name
                    )
                    reply = await handler(msg, args)
                    if reply:
                        await say(text=reply, mrkdwn=True)
                    return

            if self._default_handler is None:
                return

            msg = IncomingMessage(
                chat_id=chat_id, sender_id=user, text=text, platform=self.name
            )
            try:
                reply = await self._default_handler(msg)
            except Exception:
                logger.exception("Slack default handler raised for chat %s", chat_id)
                reply = "Sorry, something went wrong. Please try again."
            if reply:
                await say(text=reply, mrkdwn=True)


def _strip_prefix(chat_id: str) -> str:
    """Convert "sl:C0123" back to the raw Slack channel id."""
    if chat_id.startswith(f"{CHAT_ID_PREFIX}:"):
        return chat_id.split(":", 1)[1]
    return chat_id
