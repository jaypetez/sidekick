"""Chat platform abstraction.

Wraps a chat transport (Telegram, Slack, ...) behind a uniform interface
so bot.py and reminders.py can drive multiple platforms concurrently.

`chat_id` is a platform-prefixed string ("tg:-100123", "sl:C0123") so it
can key per-chat conversation history across providers without collision.

The full Telegram extraction lands in step 6 alongside the Slack
adapter; this file just locks in the contract.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(frozen=True)
class IncomingMessage:
    """A platform-neutral inbound message."""
    chat_id: str            # e.g. "tg:-100123"
    sender_id: str          # platform-native user identifier
    text: str
    platform: str           # "telegram", "slack"


CommandHandler = Callable[[IncomingMessage, list[str]], Awaitable[str | None]]
DefaultHandler = Callable[[IncomingMessage], Awaitable[str | None]]


class ChatPlatform(ABC):
    """One chat transport — Telegram, Slack, etc."""

    name: str  # short identifier used as the chat_id prefix

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        markdown: bool = True,
    ) -> None: ...

    @abstractmethod
    def register_command(self, name: str, handler: CommandHandler) -> None:
        """Register a /name command handler."""

    @abstractmethod
    def register_default_handler(self, handler: DefaultHandler) -> None:
        """Register the fall-through handler for non-command messages."""
