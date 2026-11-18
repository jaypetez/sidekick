"""Tests for the settings service — runtime_config + agent rebuild wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sidekick import runtime_config
from sidekick.services import settings as settings_service


@pytest.mark.asyncio
async def test_update_persists_to_runtime_config():
    result = await settings_service.update({"TIMEZONE": "Asia/Tokyo"})
    assert result["applied"] == ["TIMEZONE"]
    assert runtime_config.get("TIMEZONE") == "Asia/Tokyo"


@pytest.mark.asyncio
async def test_update_empty_value_clears_override(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    runtime_config.set_value("OLLAMA_MODEL", "qwen2.5:14b")
    await settings_service.update({"OLLAMA_MODEL": ""})
    # No env fallback either, so get returns None
    assert runtime_config.get("OLLAMA_MODEL") is None


@pytest.mark.asyncio
async def test_update_rejects_non_editable_keys():
    with pytest.raises(runtime_config.ConfigError):
        await settings_service.update({"TELEGRAM_BOT_TOKEN": "secret"})


@pytest.mark.asyncio
async def test_update_triggers_llm_rebuild_when_llm_keys_change():
    agent = MagicMock()
    # rebuild_client probes type() and .model — make those work
    agent.llm = MagicMock()
    agent.llm.model = "x"
    # rebuild_client calls build_llm_client() — patch it via the services.llm module
    from sidekick.services import llm as llm_service

    original = llm_service.build_llm_client
    rebuilt = MagicMock()
    rebuilt.model = "claude-haiku-4-5-20251001"
    llm_service.build_llm_client = MagicMock(return_value=rebuilt)
    try:
        result = await settings_service.update({"CLAUDE_MODEL": "claude-new"}, agent=agent)
    finally:
        llm_service.build_llm_client = original
    assert result["llm_reloaded"] is True
    assert agent.llm is rebuilt


@pytest.mark.asyncio
async def test_update_skips_rebuild_when_no_llm_keys_changed():
    agent = MagicMock()
    result = await settings_service.update({"TIMEZONE": "Asia/Tokyo"}, agent=agent)
    assert result["llm_reloaded"] is False


@pytest.mark.asyncio
async def test_set_personality_delegates_to_agent():
    agent = MagicMock()
    agent.set_personality = MagicMock(return_value="pirate")
    label = await settings_service.set_personality(agent, "pirate")
    assert label == "pirate"
    agent.set_personality.assert_called_once_with("pirate")


def test_snapshot_redacts_by_default():
    runtime_config.set_value("ANTHROPIC_API_KEY", "sk-test")
    snap = settings_service.snapshot()
    val = snap["ANTHROPIC_API_KEY"]
    assert isinstance(val, dict)
    assert val["set"] is True
    assert "sk-test" not in str(val)


@pytest.mark.asyncio
async def test_update_is_all_or_nothing():
    """A bad value anywhere in the batch must leave every key untouched."""
    with pytest.raises(runtime_config.ConfigError):
        await settings_service.update({"CLAUDE_MODEL": "claude-x", "TIMEZONE": "Not/AZone"})
    assert runtime_config.get("CLAUDE_MODEL") != "claude-x"


@pytest.mark.asyncio
async def test_update_reports_timezone_needs_restart():
    result = await settings_service.update({"TIMEZONE": "Europe/Paris"})
    assert result["restart_required"] == ["TIMEZONE"]


@pytest.mark.asyncio
async def test_update_reapplies_reminder_jobs(monkeypatch):
    scheduler = MagicMock()
    calls: list[object] = []
    monkeypatch.setattr(
        "sidekick.reminders.apply_builtin_settings",
        lambda s: calls.append(s) or [],
    )
    result = await settings_service.update({"MORNING_REMINDER_TIME": "06:45"}, scheduler=scheduler)
    assert calls == [scheduler]
    assert result["restart_required"] == []


@pytest.mark.asyncio
async def test_update_skips_reminder_jobs_for_unrelated_keys(monkeypatch):
    called = False

    def _apply(_s):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("sidekick.reminders.apply_builtin_settings", _apply)
    await settings_service.update({"CLAUDE_MODEL": "m"}, scheduler=MagicMock())
    assert called is False
