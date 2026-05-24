"""Verify the bot refuses to bind a non-loopback host without auth."""

from __future__ import annotations

import logging

import pytest

from sidekick.bot import _run_web


@pytest.mark.asyncio
async def test_refuses_non_loopback_without_token(monkeypatch, caplog):
    monkeypatch.setenv("SIDEKICK_WEB_HOST", "0.0.0.0")
    monkeypatch.delenv("SIDEKICK_WEB_AUTH_TOKEN", raising=False)
    bot_data: dict = {}
    with caplog.at_level(logging.ERROR, logger="sidekick.bot"):
        await _run_web(bot_data)
    messages = [r.getMessage() for r in caplog.records]
    assert any("non-loopback" in m for m in messages), messages
    # Importantly, no AppRunner / TCPSite should have been registered.
    assert "web_runner" not in bot_data


@pytest.mark.asyncio
async def test_refuses_ipv6_wildcard_without_token(monkeypatch, caplog):
    monkeypatch.setenv("SIDEKICK_WEB_HOST", "::")
    monkeypatch.delenv("SIDEKICK_WEB_AUTH_TOKEN", raising=False)
    bot_data: dict = {}
    with caplog.at_level(logging.ERROR, logger="sidekick.bot"):
        await _run_web(bot_data)
    assert any("non-loopback" in r.getMessage() for r in caplog.records)
    assert "web_runner" not in bot_data


@pytest.mark.asyncio
async def test_non_loopback_with_token_does_not_refuse(monkeypatch, tmp_path, caplog):
    """Setting a token is the escape hatch for non-loopback binds.

    We can't actually let the AppRunner bind (a real port is involved), so
    we patch the AppRunner setup to raise after the loopback check passes.
    The point of this test is to prove the refusal log is NOT emitted.
    """
    monkeypatch.setenv("SIDEKICK_WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", "anything-non-empty")
    monkeypatch.setenv("SIDEKICK_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(tmp_path))
    # Make ChronaryProvider() raise so the calendar path is skipped.
    import sidekick.bot as bot_mod

    class _FailingChronary:
        def __init__(self, *a, **kw):
            raise KeyError("CHRONARY_API_KEY")

    monkeypatch.setattr(
        "sidekick.calendar.chronary.ChronaryProvider", _FailingChronary, raising=True
    )

    from aiohttp import web as aiohttp_web

    class _StopHere(Exception):
        pass

    async def _boom(self):
        raise _StopHere

    monkeypatch.setattr(aiohttp_web.AppRunner, "setup", _boom)

    bot_data: dict = {}
    with caplog.at_level(logging.ERROR, logger="sidekick.bot"):
        with pytest.raises(_StopHere):
            await bot_mod._run_web(bot_data)
    assert not any("non-loopback" in r.getMessage() for r in caplog.records)
