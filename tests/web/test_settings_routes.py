"""Tests for the /settings HTML shell + the legacy POST /settings/personality."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_index_renders_form_skeleton(client):
    """The shell page contains all the editable-key form fields. Values arrive via JS."""
    resp = await client.get("/settings")
    assert resp.status == 200
    body = await resp.text()
    for name in (
        "LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "CLAUDE_MODEL",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "OLLAMA_NUM_GPU",
        "OLLAMA_NUM_CTX",
        "OLLAMA_KEEP_ALIVE",
        "TIMEZONE",
        "MORNING_REMINDER_TIME",
        "PRE_EVENT_REMINDER_MINUTES",
    ):
        assert f'name="{name}"' in body, f"settings form is missing field {name}"
    # Page wires up the JS module
    assert "/static/js/pages/settings.js" in body
    # Personality form + test-llm button hooks
    assert 'id="personality-form"' in body
    assert 'id="test-llm"' in body


@pytest.mark.asyncio
async def test_index_does_not_leak_env_secrets(client, monkeypatch):
    """Secrets must not appear in the initial HTML — JS fetches them redacted."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-tg-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-anthropic")
    resp = await client.get("/settings")
    body = await resp.text()
    assert "secret-tg-token" not in body
    assert "sk-secret-anthropic" not in body


@pytest.mark.asyncio
async def test_index_503s_without_agent(aiohttp_client):
    from sidekick.web import make_app

    app = make_app(bot_data={})
    c = await aiohttp_client(app)
    resp = await c.get("/settings")
    assert resp.status == 503


@pytest.mark.asyncio
async def test_legacy_set_personality_post_still_works(client, bot_data):
    """Browsers without JS POST to /settings/personality — the route still calls the agent."""
    resp = await client.post(
        "/settings/personality", data={"style": "pirate"}, allow_redirects=False
    )
    assert resp.status == 303
    assert resp.headers["Location"] == "/settings"
    bot_data["agent"].set_personality.assert_called_once_with("pirate")


@pytest.mark.asyncio
async def test_legacy_set_personality_accepts_empty(client, bot_data):
    resp = await client.post("/settings/personality", data={"style": ""}, allow_redirects=False)
    assert resp.status == 303
    bot_data["agent"].set_personality.assert_called_once_with("")
