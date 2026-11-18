"""sidekick-webhook CLI against a fake Chronary client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sidekick import webhook_cli

URL = "https://hooks.example.com/webhooks/chronary"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(webhook_cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("CHRONARY_API_KEY", "chr_sk_test")
    monkeypatch.setenv("CHRONARY_CALENDAR_ID", "cal_1")
    monkeypatch.setenv("PRE_EVENT_REMINDER_MINUTES", "15")
    monkeypatch.delenv("CHRONARY_WEBHOOK_ID", raising=False)


def _run(argv, client):
    return webhook_cli.main(argv, client_factory=lambda _key: client)


def test_register_creates_subscription_and_sets_calendar_default(env, capsys):
    client = MagicMock()
    client.webhooks.create.return_value = SimpleNamespace(id="wh_1", secret="whsec_abc")

    assert _run(["register", "--url", URL], client) == 0

    client.webhooks.create.assert_called_once_with(url=URL, events=["event.reminder"])
    client.calendars.update.assert_called_once_with("cal_1", default_reminders=[15])
    out = capsys.readouterr().out
    assert "CHRONARY_WEBHOOK_ID=wh_1" in out
    assert "CHRONARY_WEBHOOK_SECRET=whsec_abc" in out


@pytest.mark.parametrize("url", ["http://hooks.example.com/webhooks/chronary", "not a url"])
def test_register_requires_https(env, url):
    client = MagicMock()
    assert _run(["register", "--url", url], client) == 2
    client.webhooks.create.assert_not_called()


def test_register_refuses_when_already_configured(env, monkeypatch):
    monkeypatch.setenv("CHRONARY_WEBHOOK_ID", "wh_existing")
    client = MagicMock()
    assert _run(["register", "--url", URL], client) == 2
    client.webhooks.create.assert_not_called()


def test_register_without_lead_time_skips_calendar_update(env, monkeypatch):
    monkeypatch.setenv("PRE_EVENT_REMINDER_MINUTES", "0")
    client = MagicMock()
    client.webhooks.create.return_value = SimpleNamespace(id="wh_1", secret="s")
    assert _run(["register", "--url", URL], client) == 0
    client.calendars.update.assert_not_called()


def test_status_reports_deactivation(env, monkeypatch, capsys):
    monkeypatch.setenv("CHRONARY_WEBHOOK_ID", "wh_1")
    client = MagicMock()
    client.webhooks.get.return_value = SimpleNamespace(
        url=URL,
        events=["event.reminder"],
        active=False,
        deactivated_reason="unsafe_destination_url",
    )
    client.webhooks.list_deliveries.return_value = SimpleNamespace(data=[])
    assert _run(["status"], client) == 1
    assert "unsafe_destination_url" in capsys.readouterr().out


def test_test_polls_until_delivered(env, monkeypatch, capsys):
    monkeypatch.setenv("CHRONARY_WEBHOOK_ID", "wh_1")
    monkeypatch.setattr(webhook_cli.time, "sleep", lambda _s: None)
    client = MagicMock()
    client.webhooks.send_test.return_value = SimpleNamespace(delivery_id="whd_t")
    client.webhooks.get_delivery.side_effect = [
        SimpleNamespace(status="pending", last_response_status=None, last_error_code=None),
        SimpleNamespace(status="delivered", last_response_status=200, last_error_code=None),
    ]
    assert _run(["test"], client) == 0
    client.webhooks.send_test.assert_called_once_with("wh_1", event_type="event.reminder")
    assert "delivered" in capsys.readouterr().out


def test_delete(env, monkeypatch):
    monkeypatch.setenv("CHRONARY_WEBHOOK_ID", "wh_1")
    client = MagicMock()
    assert _run(["delete"], client) == 0
    client.webhooks.delete.assert_called_once_with("wh_1")


def test_missing_api_key_exits(env, monkeypatch):
    monkeypatch.delenv("CHRONARY_API_KEY")
    with pytest.raises(SystemExit):
        _run(["status"], MagicMock())
