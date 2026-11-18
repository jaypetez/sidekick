"""Tests for the System page, /api/system, /api/config, and setting sources."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from sidekick import __version__, runtime_config
from sidekick.web import make_app

PLANTED = {
    "TELEGRAM_BOT_TOKEN": "999:planted-telegram-ZXQ",
    "CHRONARY_API_KEY": "planted-chronary-ZXQ",
    "SLACK_BOT_TOKEN": "xoxb-planted-slack-ZXQ",
    "SIDEKICK_WEB_SESSION_SECRET": "planted-session-secret-ZXQ",
}


@pytest.fixture
def planted_secrets(monkeypatch):
    for key, value in PLANTED.items():
        monkeypatch.setenv(key, value)
    runtime_config.set_value("ANTHROPIC_API_KEY", "sk-ant-planted-ZXQ")


# --- HTML -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_page_renders_status_and_config(client, bot_data):
    bot_data["started_at"] = datetime.now(UTC) - timedelta(minutes=5)
    bot_data["telegram_enabled"] = True
    resp = await client.get("/system")
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("text/html")
    assert "no-store" in resp.headers["Cache-Control"]
    body = await resp.text()
    assert f"Sidekick {__version__}" in body
    assert "up 5m" in body
    for group in ("LLM", "Calendar", "Reminders", "Web dashboard", "Storage"):
        assert f"<h2>{group}</h2>" in body
    assert "PRE_EVENT_SOURCE" in body
    assert "local only" in body
    assert runtime_config.current_path() in body


@pytest.mark.asyncio
async def test_system_page_never_renders_secrets(client, planted_secrets):
    body = await (await client.get("/system")).text()
    assert "ZXQ" not in body
    assert "planted" not in body


@pytest.mark.asyncio
async def test_system_page_works_when_agent_not_ready(client, bot_data):
    """The page people open when things break must not 503 itself."""
    bot_data.pop("agent")
    bot_data.pop("scheduler")
    resp = await client.get("/system")
    assert resp.status == 200
    body = await resp.text()
    assert "Not ready" in body
    assert "Stopped" in body


@pytest.mark.asyncio
async def test_system_page_shows_override_source(client):
    runtime_config.set_value("OLLAMA_MODEL", "qwen-override")
    body = await (await client.get("/system")).text()
    assert "qwen-override" in body
    assert 'class="badge override"' in body


@pytest.mark.asyncio
async def test_system_page_escapes_values(client, monkeypatch):
    monkeypatch.setenv("SLACK_ALLOWED_CHANNELS", "<script>alert(1)</script>")
    body = await (await client.get("/system")).text()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


@pytest.mark.asyncio
async def test_nav_links_to_system(client):
    body = await (await client.get("/")).text()
    assert 'href="/system"' in body


@pytest.mark.asyncio
async def test_dashboard_shows_version_llm_and_platforms(client, bot_data):
    class AnthropicClient:
        model = "claude-dash-model"

    bot_data["agent"].llm = AnthropicClient()
    bot_data["telegram_enabled"] = False
    body = await (await client.get("/")).text()
    assert __version__ in body
    assert "claude-dash-model" in body
    assert "Telegram: disabled" in body


# --- JSON -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_system_envelope(client, bot_data):
    bot_data["telegram_enabled"] = True
    resp = await client.get("/api/system")
    assert resp.status == 200
    payload = await resp.json()
    assert payload["error"] is None
    data = payload["data"]
    assert data["version"] == __version__
    assert data["status"]["scheduler"] is True
    assert data["platforms"]["telegram"] == "enabled"
    assert set(data["paths"]) >= {"config_dir", "runtime_config", "database"}


@pytest.mark.asyncio
async def test_api_config_redacts_and_groups(client, planted_secrets):
    resp = await client.get("/api/config")
    assert resp.status == 200
    text = await resp.text()
    assert "ZXQ" not in text
    groups = (await resp.json())["data"]["groups"]
    entries = {s["key"]: s for g in groups for s in g["settings"]}
    assert entries["TELEGRAM_BOT_TOKEN"] == {**entries["TELEGRAM_BOT_TOKEN"], "value": None}
    assert entries["ANTHROPIC_API_KEY"]["source"] == "override"


@pytest.mark.asyncio
async def test_api_system_does_not_leak_secrets(client, planted_secrets, monkeypatch):
    text = await (await client.get("/api/system")).text()
    assert "ZXQ" not in text


@pytest.mark.asyncio
async def test_api_settings_reports_sources_and_defaults(client, monkeypatch):
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu-box:11434")
    runtime_config.set_value("OLLAMA_MODEL", "qwen")
    data = (await (await client.get("/api/settings")).json())["data"]
    assert data["sources"]["CLAUDE_MODEL"] == "default"
    assert data["sources"]["OLLAMA_BASE_URL"] == "env"
    assert data["sources"]["OLLAMA_MODEL"] == "override"
    assert data["defaults"]["CLAUDE_MODEL"] == "claude-haiku-4-5-20251001"
    assert set(data["sources"]) == set(data["editable_keys"])


@pytest.mark.asyncio
async def test_api_settings_patch_returns_updated_sources(client, monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    runtime_config.set_value("OLLAMA_MODEL", "qwen")
    resp = await client.patch("/api/settings", json={"OLLAMA_MODEL": ""})
    assert resp.status == 200
    data = (await resp.json())["data"]
    assert data["sources"]["OLLAMA_MODEL"] == "default"


@pytest.mark.asyncio
async def test_settings_page_still_serves_shell(client):
    resp = await client.get("/settings")
    assert resp.status == 200
    assert "/static/js/pages/settings.js" in await resp.text()


# --- auth -------------------------------------------------------------------


@pytest_asyncio.fixture
async def auth_client(aiohttp_client, bot_data, monkeypatch):
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", "s3cret-token-0123456789")
    return await aiohttp_client(make_app(bot_data=bot_data))


@pytest.mark.parametrize("path", ["/system", "/api/system", "/api/config"])
@pytest.mark.asyncio
async def test_system_routes_require_auth_when_configured(auth_client, path):
    assert (await auth_client.get(path)).status == 401
    ok = await auth_client.get(path, headers={"Authorization": "Bearer s3cret-token-0123456789"})
    assert ok.status == 200
    assert "s3cret-token-0123456789" not in await ok.text()


@pytest.mark.asyncio
async def test_plain_health_shape_unchanged(client):
    payload = await (await client.get("/health")).json()
    assert set(payload) == {"scheduler", "mcp", "reminders", "tools"}


@pytest.mark.asyncio
async def test_platform_tiles_are_neutral_when_disabled(client, bot_data, monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    bot_data["telegram_enabled"] = False
    body = await (await client.get("/system")).text()
    assert '<p class="status neutral">Disabled</p>' in body
    assert '<p class="status ok">Disabled</p>' not in body


@pytest.mark.asyncio
async def test_platform_tile_red_when_slack_dropped(client, bot_data, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-1")
    platform = MagicMock()
    platform.is_running = False
    bot_data["slack_platform"] = platform
    body = await (await client.get("/system")).text()
    assert '<p class="status down">Stopped</p>' in body
