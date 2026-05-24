"""Tests for /settings routes."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_index_shows_current_personality(client, bot_data):
    bot_data["agent"].personality = "Respond like a pirate."
    resp = await client.get("/settings")
    assert resp.status == 200
    body = await resp.text()
    assert "Respond like a pirate." in body


@pytest.mark.asyncio
async def test_index_lists_personality_presets(client):
    """The datalist should include the known presets so the input autocompletes."""
    resp = await client.get("/settings")
    body = await resp.text()
    for preset in ("snarky", "pirate", "formal", "butler", "surfer"):
        assert preset in body


@pytest.mark.asyncio
async def test_index_shows_env_summary_without_secrets(client, monkeypatch):
    monkeypatch.setenv("TIMEZONE", "America/Chicago")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    # Tokens that must NOT show up:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-key")
    resp = await client.get("/settings")
    body = await resp.text()
    assert "America/Chicago" in body
    assert "claude-haiku-4-5-20251001" in body
    assert "secret-token" not in body
    assert "secret-key" not in body


@pytest.mark.asyncio
async def test_set_personality_calls_agent(client, bot_data):
    resp = await client.post(
        "/settings/personality", data={"style": "pirate"}, allow_redirects=False
    )
    assert resp.status == 303
    assert resp.headers["Location"] == "/settings"
    bot_data["agent"].set_personality.assert_called_once_with("pirate")


@pytest.mark.asyncio
async def test_set_personality_accepts_empty_to_reset(client, bot_data):
    """Empty style is the documented way to clear personality back to default."""
    resp = await client.post("/settings/personality", data={"style": ""}, allow_redirects=False)
    assert resp.status == 303
    bot_data["agent"].set_personality.assert_called_once_with("")


@pytest.mark.asyncio
async def test_index_503s_without_agent(aiohttp_client):
    from sidekick.web import make_app

    app = make_app(bot_data={})
    c = await aiohttp_client(app)
    resp = await c.get("/settings")
    assert resp.status == 503
