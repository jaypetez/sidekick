"""Tests for sidekick.services.system."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from sidekick import __version__, runtime_config
from sidekick.services import system


class AnthropicClient:  # name matters: maps to provider "anthropic"
    model = "claude-test-model"


class OllamaClient:
    model = "llama-test"


def _bot_data(**extra):
    scheduler = MagicMock()
    scheduler.running = True
    scheduler.get_jobs.return_value = [object(), object()]
    agent = MagicMock()
    agent.tools = [{"name": "a"}]
    agent.llm = AnthropicClient()
    mcp_task = MagicMock()
    mcp_task.done.return_value = False
    return {"scheduler": scheduler, "agent": agent, "mcp_task": mcp_task, **extra}


def _entries():
    return {s["key"]: s for g in system.config_report() for s in g["settings"]}


# --- status -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_counts_and_flags():
    result = await system.status(_bot_data())
    assert result["scheduler"] is True
    assert result["mcp"] is True
    assert result["reminders"] == 2
    assert result["tools"] == 1
    assert result["webhook"]["last_received_at"] is None


@pytest.mark.asyncio
async def test_status_with_nothing_running():
    result = await system.status({})
    assert result == {
        "scheduler": False,
        "mcp": False,
        "reminders": 0,
        "tools": 0,
        "webhook": result["webhook"],
    }


@pytest.mark.asyncio
async def test_status_reports_last_webhook_delivery():
    log = MagicMock()
    log.last_received_at = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    result = await system.status({}, webhook_log=log)
    assert result["webhook"]["last_received_at"] == "2026-01-02T03:04:00+00:00"


# --- overview ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_core_fields(monkeypatch):
    monkeypatch.delenv("SIDEKICK_WEB_HOST", raising=False)
    monkeypatch.delenv("SIDEKICK_WEB_AUTH_TOKEN", raising=False)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    data = await system.overview(
        _bot_data(started_at=now - timedelta(hours=2), telegram_enabled=True), now=now
    )
    assert data["version"] == __version__
    assert data["uptime_seconds"] == 7200
    assert data["started_at"] == (now - timedelta(hours=2)).isoformat()
    assert data["llm"] == {"provider": "anthropic", "model": "claude-test-model"}
    assert data["platforms"]["telegram"] == "enabled"
    assert data["web"] == {
        "host": "127.0.0.1",
        "port": 8080,
        "auth_enabled": False,
        "loopback": True,
    }
    assert data["paths"]["runtime_config"] == runtime_config.current_path()
    json.dumps(data)  # must be JSON-serialisable for /api/system


@pytest.mark.asyncio
async def test_overview_unknown_uptime_and_missing_agent():
    data = await system.overview({})
    assert data["uptime_seconds"] is None
    assert data["started_at"] is None
    assert data["llm"] == {"provider": None, "model": None}
    assert data["platforms"]["telegram"] == "unknown"


@pytest.mark.asyncio
async def test_overview_ollama_provider():
    bot_data = _bot_data()
    bot_data["agent"].llm = OllamaClient()
    data = await system.overview(bot_data)
    assert data["llm"] == {"provider": "ollama", "model": "llama-test"}


@pytest.mark.asyncio
async def test_overview_non_loopback_with_auth(monkeypatch):
    monkeypatch.setenv("SIDEKICK_WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", "x" * 32)
    monkeypatch.setenv("SIDEKICK_WEB_PORT", "9090")
    data = await system.overview({})
    assert data["web"] == {"host": "0.0.0.0", "port": 9090, "auth_enabled": True, "loopback": False}
    assert "x" * 32 not in json.dumps(data)


def _slack_env(monkeypatch, configured):
    if configured:
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
        monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-1")
    else:
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)


@pytest.mark.parametrize(
    ("platform_running", "task_done", "configured", "expected"),
    [
        (None, None, False, "disabled"),
        (None, None, True, "stopped"),  # configured but adapter never started
        (None, False, True, "starting"),  # _run_slack still connecting
        (None, True, True, "stopped"),  # _run_slack crashed before the platform existed
        (True, True, True, "running"),  # _run_slack returns once started — still running
        (False, True, True, "stopped"),  # socket-mode task died
    ],
)
@pytest.mark.asyncio
async def test_overview_slack_state(monkeypatch, platform_running, task_done, configured, expected):
    _slack_env(monkeypatch, configured)
    bot_data: dict = {"telegram_enabled": False}
    if task_done is not None:
        task = MagicMock()
        task.done.return_value = task_done
        bot_data["slack_task"] = task
    if platform_running is not None:
        platform = MagicMock()
        platform.is_running = platform_running
        bot_data["slack_platform"] = platform
    data = await system.overview(bot_data)
    assert data["platforms"]["slack"] == expected
    assert data["platforms"]["telegram"] == "disabled"


@pytest.mark.asyncio
async def test_overview_bad_port_does_not_crash(monkeypatch):
    monkeypatch.setenv("SIDEKICK_WEB_PORT", "eighty")
    assert (await system.overview({}))["web"]["port"] == "eighty"


@pytest.mark.asyncio
async def test_status_can_skip_webhook_block():
    result = await system.status(_bot_data(), include_webhook=False)
    assert set(result) == {"scheduler", "mcp", "reminders", "tools"}


@pytest.mark.asyncio
async def test_overview_reminder_chat(monkeypatch):
    monkeypatch.setenv("REMINDER_CHAT_ID", "12345")
    assert (await system.overview({}))["reminders"]["chat_configured"] is True
    monkeypatch.setenv("REMINDER_CHAT_ID", "  ")
    assert (await system.overview({}))["reminders"]["chat_configured"] is False


# --- config_report ----------------------------------------------------------


def test_config_report_groups_in_display_order():
    groups = [g["group"] for g in system.config_report()]
    assert groups[0] == "LLM"
    assert groups == [g for g in system.config_catalog.GROUPS if g in groups]


def test_config_report_never_contains_secret_values(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:telegram-secret-QZ1")
    monkeypatch.setenv("CHRONARY_API_KEY", "chronary-secret-QZ2")
    runtime_config.set_value("ANTHROPIC_API_KEY", "sk-ant-secret-QZ3")
    report = system.config_report()
    blob = json.dumps(report)
    for secret in ("telegram-secret-value", "chronary-secret-QZ2", "sk-ant-secret-QZ3"):
        assert secret not in blob
    # No preview tail either (settings shows "…QZ3"; the report must not).
    assert "QZ" not in blob
    entries = _entries()
    assert entries["ANTHROPIC_API_KEY"]["value"] is None
    assert entries["ANTHROPIC_API_KEY"]["display"] == "set"
    assert entries["ANTHROPIC_API_KEY"]["source"] == "override"
    assert entries["TELEGRAM_BOT_TOKEN"]["source"] == "env"


def test_config_report_unset_secret(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    entry = _entries()["SLACK_BOT_TOKEN"]
    assert entry["display"] == "not set"
    assert entry["source"] == "default"
    assert entry["secret"] is True


def test_config_report_values_and_defaults(monkeypatch):
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    monkeypatch.setenv("SIDEKICK_WEB_PORT", "8181")
    monkeypatch.setenv("SLACK_ALLOWED_CHANNELS", "")
    monkeypatch.delenv("REMINDER_CHAT_ID", raising=False)
    entries = _entries()
    assert entries["CLAUDE_MODEL"]["value"] is None
    assert entries["CLAUDE_MODEL"]["display"] == "claude-haiku-4-5-20251001"
    assert entries["CLAUDE_MODEL"]["source"] == "default"
    assert entries["CLAUDE_MODEL"]["editable"] is True
    assert entries["SIDEKICK_WEB_PORT"]["display"] == "8181"
    assert entries["SIDEKICK_WEB_PORT"]["editable"] is False
    assert entries["SLACK_ALLOWED_CHANNELS"]["display"] == "(empty)"
    assert entries["REMINDER_CHAT_ID"]["display"] == "not set"
    assert entries["TIMEZONE"]["restart_required"] is True


# --- format_uptime ----------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(None, "unknown"), (0, "0s"), (42, "42s"), (125, "2m 5s"), (3720, "1h 2m"), (90000, "1d 1h")],
)
def test_format_uptime(seconds, expected):
    assert system.format_uptime(seconds) == expected


def test_empty_env_value_shows_effective_default(monkeypatch):
    """`TIMEZONE=` in .env means the default applies (callers use `or default`)."""
    monkeypatch.setenv("TIMEZONE", "")
    entry = _entries()["TIMEZONE"]
    assert entry["display"] == "America/Chicago"
    assert entry["source"] == "env"


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("http://user:hunter2@gpu-box:11434", "http://***@gpu-box:11434"),
        ("https://token@example.com/path", "https://***@example.com/path"),
        ("http://gpu-box:11434", "http://gpu-box:11434"),
    ],
)
def test_url_credentials_are_masked(monkeypatch, raw, shown):
    monkeypatch.setenv("OLLAMA_BASE_URL", raw)
    entry = _entries()["OLLAMA_BASE_URL"]
    assert entry["display"] == shown
    assert entry["value"] == shown
    assert "hunter2" not in json.dumps(system.config_report())


def test_webhook_secret_from_file_shows_set(monkeypatch, tmp_path):
    monkeypatch.delenv("CHRONARY_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(tmp_path))
    (tmp_path / "chronary_webhook.secret").write_text("whsec_file_only_QQ")
    entry = _entries()["CHRONARY_WEBHOOK_SECRET"]
    assert entry["display"] == "set"
    assert entry["source"] == "file"
    assert "QQ" not in json.dumps(system.config_report())


def test_unset_secret_with_fallback_explains_itself(monkeypatch):
    monkeypatch.delenv("SIDEKICK_WEB_SESSION_SECRET", raising=False)
    monkeypatch.delenv("SIDEKICK_API_TOKEN", raising=False)
    entries = _entries()
    assert entries["SIDEKICK_WEB_SESSION_SECRET"]["display"].startswith("auto-generated")
    assert "falls back" in entries["SIDEKICK_API_TOKEN"]["display"]
