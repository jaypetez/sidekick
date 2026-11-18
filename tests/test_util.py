"""Tests for the env helpers in sidekick.util and SlackPlatform.is_running."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sidekick import util


@pytest.mark.parametrize(
    ("host", "expected"),
    [("127.0.0.1", True), (" LOCALHOST ", True), ("::1", True), ("0.0.0.0", False)],
)
def test_is_loopback_host(host, expected):
    assert util.is_loopback_host(host) is expected


def test_web_auth_token(monkeypatch):
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", "  abc  ")
    assert util.web_auth_token() == "abc"
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", "   ")
    assert util.web_auth_token() is None


def test_web_bind(monkeypatch):
    monkeypatch.delenv("SIDEKICK_WEB_HOST", raising=False)
    monkeypatch.delenv("SIDEKICK_WEB_PORT", raising=False)
    assert util.web_bind() == ("127.0.0.1", 8080)
    monkeypatch.setenv("SIDEKICK_WEB_PORT", "nope")
    with pytest.raises(ValueError):
        util.web_bind()


def test_slack_configured(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    assert util.slack_configured() is False
    monkeypatch.setenv("SLACK_APP_TOKEN", "y")
    assert util.slack_configured() is True


def test_slack_platform_is_running():
    from sidekick.platforms.slack import SlackPlatform

    platform = SlackPlatform.__new__(SlackPlatform)
    platform._app_task = None
    assert platform.is_running is False
    task = MagicMock()
    task.done.return_value = False
    platform._app_task = task
    assert platform.is_running is True
    task.done.return_value = True
    assert platform.is_running is False
