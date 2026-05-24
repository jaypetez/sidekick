"""Verify the MCP subprocess env builder only exposes allowlisted vars."""

from sidekick.bot import _MCP_ENV_ALLOWLIST, _build_mcp_env


def test_build_mcp_env_drops_unrelated_secrets(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-secret")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-secret")
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", "web-secret")
    monkeypatch.setenv("CHRONARY_API_KEY", "ck-secret")
    monkeypatch.setenv("CHRONARY_AGENT_ID", "agent-123")
    monkeypatch.setenv("CHRONARY_CALENDAR_ID", "cal-456")
    monkeypatch.setenv("TIMEZONE", "America/Chicago")

    env = _build_mcp_env()

    # Chronary + timezone propagate
    assert env.get("CHRONARY_API_KEY") == "ck-secret"
    assert env.get("CHRONARY_AGENT_ID") == "agent-123"
    assert env.get("CHRONARY_CALENDAR_ID") == "cal-456"
    assert env.get("TIMEZONE") == "America/Chicago"

    # Secrets unrelated to the MCP subprocess do NOT propagate
    assert "SLACK_BOT_TOKEN" not in env
    assert "SLACK_APP_TOKEN" not in env
    assert "TELEGRAM_BOT_TOKEN" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "SIDEKICK_WEB_AUTH_TOKEN" not in env


def test_mcp_env_allowlist_does_not_include_chat_secrets():
    forbidden = {
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "ANTHROPIC_API_KEY",
        "SIDEKICK_WEB_AUTH_TOKEN",
    }
    assert forbidden.isdisjoint(_MCP_ENV_ALLOWLIST)


def test_build_mcp_env_ignores_unknown_vars(monkeypatch):
    monkeypatch.setenv("SOMETHING_RANDOM", "value")
    env = _build_mcp_env()
    assert "SOMETHING_RANDOM" not in env
