"""Invalid reminder schedules are client errors (400), not 500/502/404."""

from __future__ import annotations

import pytest


@pytest.fixture
def real_reminder_store(tmp_reminders_file):
    """Use the real add/update functions against an isolated reminders file."""
    return tmp_reminders_file


@pytest.mark.asyncio
async def test_api_create_out_of_range_hour_is_400(client, real_reminder_store):
    resp = await client.post("/api/reminders", json={"message": "x", "hour": 25, "minute": 0})
    assert resp.status == 400
    payload = await resp.json()
    assert payload["error"]["code"] == "invalid_field"
    assert "hour" in payload["error"]["message"]


@pytest.mark.asyncio
async def test_api_update_invalid_minute_is_400_not_404(client, monkeypatch):
    def invalid(*_args, **_kwargs):
        raise ValueError("minute must be an integer 0-59, got 99")

    monkeypatch.setattr("sidekick.services.reminders._update_reminder", invalid)
    resp = await client.patch("/api/reminders/reminder_abc", json={"minute": 99})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_html_create_invalid_schedule_is_400(client, monkeypatch):
    def invalid(*_args, **_kwargs):
        raise ValueError("hour must be an integer 0-23, got 30")

    monkeypatch.setattr("sidekick.web.handlers.reminders.add_reminder", invalid)
    resp = await client.post(
        "/reminders", data={"message": "x", "hour": "30", "minute": "0"}, allow_redirects=False
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_html_update_invalid_schedule_is_400(client, monkeypatch):
    def invalid(*_args, **_kwargs):
        raise ValueError("bad day_of_week")

    monkeypatch.setattr("sidekick.web.handlers.reminders.update_reminder", invalid)
    resp = await client.post(
        "/reminders/reminder_abc", data={"day_of_week": "weekdays"}, allow_redirects=False
    )
    assert resp.status == 400
