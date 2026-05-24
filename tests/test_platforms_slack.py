"""Smoke tests for SlackPlatform.

These don't open a real socket-mode connection — they only verify
handler registration and chat_id prefixing logic, which is enough to
catch regressions in the adapter wiring.
"""

import asyncio

import pytest

from sidekick.platforms.base import IncomingMessage
from sidekick.platforms.slack import SlackPlatform, _strip_prefix


@pytest.fixture
def slack_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")


# -------------------------------------------------------------------
# Adapter wiring
# -------------------------------------------------------------------


def test_init_reads_tokens_from_env(slack_env):
    p = SlackPlatform()
    assert p._bot_token == "xoxb-test"
    assert p._app_token == "xapp-test"


def test_register_command_and_default(slack_env):
    p = SlackPlatform()

    async def cmd(msg, args):
        return "ok"

    async def default(msg):
        return "default"

    p.register_command("reset", cmd)
    p.register_default_handler(default)

    assert "reset" in p._commands
    assert p._default_handler is default


# -------------------------------------------------------------------
# chat_id prefix handling
# -------------------------------------------------------------------


def test_strip_prefix_removes_sl_prefix():
    assert _strip_prefix("sl:C012345") == "C012345"


def test_strip_prefix_passthrough_for_unprefixed():
    """If someone passes a raw channel id, don't mangle it."""
    assert _strip_prefix("C012345") == "C012345"


# -------------------------------------------------------------------
# IncomingMessage shape
# -------------------------------------------------------------------


def test_incoming_message_is_frozen():
    """IncomingMessage is a frozen dataclass — defensive immutability."""
    msg = IncomingMessage(chat_id="sl:C1", sender_id="U1", text="hi", platform="slack")
    with pytest.raises(Exception):
        msg.text = "mutated"  # type: ignore[misc]
