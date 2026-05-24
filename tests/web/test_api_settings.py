"""Tests for /api/settings endpoints."""

from __future__ import annotations

import pytest

from sidekick import runtime_config


@pytest.mark.asyncio
async def test_settings_index_redacts_anthropic_key(client):
    runtime_config.set_value("ANTHROPIC_API_KEY", "sk-secret-tail")
    resp = await client.get("/api/settings")
    assert resp.status == 200
    payload = await resp.json()
    val = payload["data"]["settings"]["ANTHROPIC_API_KEY"]
    assert isinstance(val, dict)
    assert val["set"] is True
    assert "sk-secret-tail" not in str(val)
    # The full response body must not contain the secret anywhere
    body = await (await client.get("/api/settings")).text()
    assert "sk-secret-tail" not in body


@pytest.mark.asyncio
async def test_settings_index_includes_editable_keys(client):
    resp = await client.get("/api/settings")
    payload = await resp.json()
    assert "OLLAMA_NUM_GPU" in payload["data"]["editable_keys"]
    assert "LLM_PROVIDER" in payload["data"]["editable_keys"]
    assert "TELEGRAM_BOT_TOKEN" not in payload["data"]["editable_keys"]


@pytest.mark.asyncio
async def test_settings_update_persists_value(client):
    resp = await client.patch("/api/settings", json={"OLLAMA_NUM_GPU": "999"})
    assert resp.status == 200
    payload = await resp.json()
    assert "OLLAMA_NUM_GPU" in payload["data"]["applied"]
    assert runtime_config.get("OLLAMA_NUM_GPU") == "999"


@pytest.mark.asyncio
async def test_settings_update_clears_with_empty_string(client, monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_GPU", raising=False)
    runtime_config.set_value("OLLAMA_NUM_GPU", "42")
    resp = await client.patch("/api/settings", json={"OLLAMA_NUM_GPU": ""})
    assert resp.status == 200
    assert runtime_config.get("OLLAMA_NUM_GPU") is None


@pytest.mark.asyncio
async def test_settings_update_rejects_non_editable_key(client):
    resp = await client.patch("/api/settings", json={"TELEGRAM_BOT_TOKEN": "abc"})
    assert resp.status == 400
    payload = await resp.json()
    assert payload["error"]["code"] == "not_editable"


@pytest.mark.asyncio
async def test_settings_update_triggers_llm_rebuild(client, bot_data, monkeypatch):
    """Updating CLAUDE_MODEL should call build_llm_client() and swap agent.llm."""
    from sidekick.services import llm as llm_service

    rebuilt = type("LLM", (), {"model": "claude-new"})()
    monkeypatch.setattr(llm_service, "build_llm_client", lambda: rebuilt)
    resp = await client.patch("/api/settings", json={"CLAUDE_MODEL": "claude-new"})
    assert resp.status == 200
    payload = await resp.json()
    assert payload["data"]["llm_reloaded"] is True
    assert bot_data["agent"].llm is rebuilt


@pytest.mark.asyncio
async def test_settings_update_requires_json_object(client):
    resp = await client.patch(
        "/api/settings", data="just a string", headers={"Content-Type": "application/json"}
    )
    # Either invalid_json (parse error) or invalid_body (string instead of object)
    payload = await resp.json()
    assert payload["error"]["code"] in {"invalid_json", "invalid_body"}


@pytest.mark.asyncio
async def test_settings_update_requires_non_empty(client):
    resp = await client.patch("/api/settings", json={})
    assert resp.status == 400
    payload = await resp.json()
    assert payload["error"]["code"] == "missing_field"


@pytest.mark.asyncio
async def test_personality_get_returns_current_and_presets(client, bot_data):
    bot_data["agent"].personality = "arr matey"
    resp = await client.get("/api/personality")
    assert resp.status == 200
    payload = await resp.json()
    assert payload["data"]["current"] == "arr matey"
    assert "pirate" in payload["data"]["presets"]


@pytest.mark.asyncio
async def test_personality_update_calls_agent(client, bot_data):
    bot_data["agent"].set_personality = lambda style: "snarky"
    resp = await client.patch("/api/personality", json={"style": "snarky"})
    assert resp.status == 200
    payload = await resp.json()
    assert payload["data"]["label"] == "snarky"


@pytest.mark.asyncio
async def test_test_llm_returns_probe_result(client, bot_data, monkeypatch):
    async def fake_probe(agent, *, prompt="..."):
        return {"ok": True, "reply": "OK", "model": "test", "provider": "T"}

    monkeypatch.setattr("sidekick.web.api.settings.llm_service.probe", fake_probe)
    resp = await client.post("/api/settings/test-llm")
    assert resp.status == 200
    payload = await resp.json()
    assert payload["data"]["reply"] == "OK"


@pytest.mark.asyncio
async def test_test_llm_returns_502_on_probe_failure(client, monkeypatch):
    async def fake_probe(agent, *, prompt="..."):
        return {"ok": False, "error": "boom"}

    monkeypatch.setattr("sidekick.web.api.settings.llm_service.probe", fake_probe)
    resp = await client.post("/api/settings/test-llm")
    assert resp.status == 502
    payload = await resp.json()
    assert payload["error"]["code"] == "probe_failed"
