"""Allowlist + rate-limit checks for SlackPlatform._on_message."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from sidekick import ratelimit
from sidekick.platforms.slack import SlackPlatform


@pytest.fixture(autouse=True)
def _slack_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.delenv("SLACK_ALLOWED_CHANNELS", raising=False)
    ratelimit.reset_default_limiter()
    yield
    ratelimit.reset_default_limiter()


def _capture_on_message(platform):
    captured = {}

    def fake_event(name):
        def register(fn):
            captured[name] = fn
            return fn

        return register

    app = MagicMock()
    app.event = fake_event
    platform._register_listeners(app)
    return captured["message"]


@pytest.mark.asyncio
async def test_denied_user_does_not_call_default(monkeypatch, caplog):
    monkeypatch.delenv("SLACK_ALLOWED_USER_IDS", raising=False)
    p = SlackPlatform()
    on_message = _capture_on_message(p)
    default = AsyncMock(return_value="should not run")
    p.register_default_handler(default)
    say = AsyncMock()

    with caplog.at_level(logging.WARNING, logger="sidekick.platforms.slack"):
        await on_message({"text": "hi", "channel": "C1", "user": "U999"}, say)

    default.assert_not_awaited()
    say.assert_awaited_once()
    assert "allowlist" in say.await_args.kwargs["text"].lower()
    msgs = " ".join(rec.getMessage() for rec in caplog.records)
    assert "user_id=U999" in msgs


@pytest.mark.asyncio
async def test_allowed_user_calls_default(monkeypatch):
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "U01XYZ,U02ABC")
    p = SlackPlatform()
    on_message = _capture_on_message(p)
    default = AsyncMock(return_value="hello")
    p.register_default_handler(default)
    say = AsyncMock()

    await on_message({"text": "hi", "channel": "C1", "user": "U01XYZ"}, say)

    default.assert_awaited_once()
    say.assert_awaited_once()
    assert say.await_args.kwargs["text"] == "hello"


@pytest.mark.asyncio
async def test_channel_allowlist_blocks_other_channels(monkeypatch, caplog):
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "U1")
    monkeypatch.setenv("SLACK_ALLOWED_CHANNELS", "C_GOOD")
    p = SlackPlatform()
    on_message = _capture_on_message(p)
    default = AsyncMock(return_value="never")
    p.register_default_handler(default)
    say = AsyncMock()

    with caplog.at_level(logging.WARNING, logger="sidekick.platforms.slack"):
        await on_message({"text": "hi", "channel": "C_BAD", "user": "U1"}, say)

    default.assert_not_awaited()
    say.assert_not_awaited()
    msgs = " ".join(rec.getMessage() for rec in caplog.records)
    assert "channel_not_allowlisted" in msgs


@pytest.mark.asyncio
async def test_channel_allowlist_permits_listed_channel(monkeypatch):
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "U1")
    monkeypatch.setenv("SLACK_ALLOWED_CHANNELS", "C_GOOD")
    p = SlackPlatform()
    on_message = _capture_on_message(p)
    default = AsyncMock(return_value="hi back")
    p.register_default_handler(default)
    say = AsyncMock()

    await on_message({"text": "hi", "channel": "C_GOOD", "user": "U1"}, say)

    default.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limit_blocks_excess_messages(monkeypatch):
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "U1")
    monkeypatch.setenv("SIDEKICK_RATE_LIMIT_MAX", "2")
    monkeypatch.setenv("SIDEKICK_RATE_LIMIT_WINDOW_SECONDS", "60")
    ratelimit.reset_default_limiter()

    p = SlackPlatform()
    on_message = _capture_on_message(p)
    default = AsyncMock(return_value="ok")
    p.register_default_handler(default)
    say = AsyncMock()

    for _ in range(3):
        await on_message({"text": "hi", "channel": "C", "user": "U1"}, say)

    # 2 default invocations + 1 rate-limit say.
    assert default.await_count == 2
    last_call = say.await_args_list[-1]
    assert "too quickly" in last_call.kwargs["text"].lower()
