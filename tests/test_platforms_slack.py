"""Smoke tests for SlackPlatform.

These don't open a real socket-mode connection — they only verify
handler registration and chat_id prefixing logic, which is enough to
catch regressions in the adapter wiring.
"""

import dataclasses
from unittest.mock import AsyncMock, MagicMock

import pytest

from sidekick.platforms.base import IncomingMessage
from sidekick.platforms.slack import SlackPlatform, _strip_prefix


@pytest.fixture
def slack_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    # Allow all the synthetic Slack users the existing tests use.
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "U,U1,U2")
    monkeypatch.delenv("SLACK_ALLOWED_CHANNELS", raising=False)
    from sidekick import ratelimit

    ratelimit.reset_default_limiter()
    yield
    ratelimit.reset_default_limiter()


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
    with pytest.raises(dataclasses.FrozenInstanceError):
        msg.text = "mutated"  # type: ignore[misc]


# -------------------------------------------------------------------
# _on_message listener behaviour
#
# slack-bolt registers an inner function via @app.event("message"); we recover
# it by stubbing app.event to capture the decorated handler, then call it
# directly with synthetic event dicts.
# -------------------------------------------------------------------


def _make_platform_with_captured_listener(slack_env):
    """Construct a SlackPlatform and return (platform, captured _on_message)."""
    p = SlackPlatform()
    captured: dict[str, object] = {}

    def fake_event_decorator(name):
        def register(fn):
            captured[name] = fn
            return fn

        return register

    app = MagicMock()
    app.event = fake_event_decorator
    p._register_listeners(app)
    return p, captured["message"]


@pytest.mark.asyncio
async def test_on_message_skips_subtype_events(slack_env):
    """Channel join/leave events come with a `subtype` — must be ignored."""
    p, on_message = _make_platform_with_captured_listener(slack_env)
    default = AsyncMock(return_value="should not run")
    p.register_default_handler(default)
    say = AsyncMock()
    await on_message({"subtype": "channel_join", "text": "hi", "channel": "C", "user": "U"}, say)
    default.assert_not_awaited()
    say.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_skips_bot_messages(slack_env):
    p, on_message = _make_platform_with_captured_listener(slack_env)
    default = AsyncMock(return_value="x")
    p.register_default_handler(default)
    say = AsyncMock()
    await on_message({"bot_id": "B1", "text": "hi", "channel": "C", "user": "U"}, say)
    default.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_routes_command(slack_env):
    p, on_message = _make_platform_with_captured_listener(slack_env)
    cmd = AsyncMock(return_value="reset done")
    p.register_command("reset", cmd)
    say = AsyncMock()
    await on_message({"text": "/reset", "channel": "C123", "user": "U1"}, say)
    cmd.assert_awaited_once()
    msg, args = cmd.await_args.args
    assert msg.chat_id == "sl:C123"
    assert msg.platform == "slack"
    assert args == []
    say.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_message_unknown_command_falls_through_to_default(slack_env):
    """If command name has no handler, treat as a regular message."""
    p, on_message = _make_platform_with_captured_listener(slack_env)
    default = AsyncMock(return_value="default ran")
    p.register_default_handler(default)
    say = AsyncMock()
    await on_message({"text": "/unknown extra arg", "channel": "C", "user": "U"}, say)
    # Default handler still fires because no /unknown command was registered.
    default.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_message_routes_default(slack_env):
    p, on_message = _make_platform_with_captured_listener(slack_env)
    default = AsyncMock(return_value="hello back")
    p.register_default_handler(default)
    say = AsyncMock()
    await on_message({"text": "hi", "channel": "C123", "user": "U1"}, say)
    default.assert_awaited_once()
    say.assert_awaited_once()
    assert say.await_args.kwargs["text"] == "hello back"


@pytest.mark.asyncio
async def test_on_message_default_handler_exception_yields_apology(slack_env):
    p, on_message = _make_platform_with_captured_listener(slack_env)
    default = AsyncMock(side_effect=RuntimeError("boom"))
    p.register_default_handler(default)
    say = AsyncMock()
    await on_message({"text": "hi", "channel": "C123", "user": "U1"}, say)
    say.assert_awaited_once()
    assert "something went wrong" in say.await_args.kwargs["text"].lower()


@pytest.mark.asyncio
async def test_on_message_no_default_handler_silent(slack_env):
    p, on_message = _make_platform_with_captured_listener(slack_env)
    # No default registered.
    say = AsyncMock()
    await on_message({"text": "hi", "channel": "C", "user": "U"}, say)
    say.assert_not_awaited()


# -------------------------------------------------------------------
# send_message / start / stop
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_strips_prefix_before_posting(slack_env):
    p = SlackPlatform()
    p._app = MagicMock()
    p._app.client.chat_postMessage = AsyncMock()
    await p.send_message("sl:C999", "hello", markdown=False)
    p._app.client.chat_postMessage.assert_awaited_once_with(
        channel="C999", text="hello", mrkdwn=False
    )


@pytest.mark.asyncio
async def test_send_message_before_start_raises(slack_env):
    p = SlackPlatform()
    with pytest.raises(RuntimeError, match="before start"):
        await p.send_message("sl:C1", "hi")


@pytest.mark.asyncio
async def test_stop_is_safe_to_call_before_start(slack_env):
    """No socket handler / app task to clean up — stop should be a no-op, not crash."""
    p = SlackPlatform()
    await p.stop()
