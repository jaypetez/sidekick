"""Tests for /api/reminders endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_reminders_envelope(client, monkeypatch):
    monkeypatch.setattr(
        "sidekick.services.reminders.get_all_reminders",
        lambda _scheduler: [{"id": "morning_summary", "type": "cron", "paused": False}],
    )
    resp = await client.get("/api/reminders")
    assert resp.status == 200
    payload = await resp.json()
    assert "reminders" in payload["data"]
    assert "builtin_ids" in payload["data"]
    assert "morning_summary" in payload["data"]["builtin_ids"]


@pytest.mark.asyncio
async def test_create_reminder_validates_message(client):
    resp = await client.post("/api/reminders", json={"message": "", "hour": 7, "minute": 30})
    assert resp.status == 400
    payload = await resp.json()
    assert payload["error"]["code"] == "missing_field"


@pytest.mark.asyncio
async def test_create_reminder_validates_time(client):
    resp = await client.post(
        "/api/reminders", json={"message": "stretch", "hour": "noon", "minute": 30}
    )
    assert resp.status == 400
    payload = await resp.json()
    assert payload["error"]["code"] == "invalid_field"


@pytest.mark.asyncio
async def test_create_reminder_happy_path(client, monkeypatch):
    captured: dict = {}

    def fake_add(scheduler, agent, message, hour, minute, chat_id, day_of_week):
        captured["message"] = message
        captured["hour"] = hour
        captured["minute"] = minute
        captured["day_of_week"] = day_of_week
        return {"id": "reminder_1", "message": message}

    monkeypatch.setattr("sidekick.services.reminders._add_reminder", fake_add)
    resp = await client.post(
        "/api/reminders",
        json={"message": "stretch", "hour": 9, "minute": 0, "day_of_week": "mon,fri"},
    )
    assert resp.status == 201
    payload = await resp.json()
    assert payload["data"]["id"] == "reminder_1"
    assert captured == {"message": "stretch", "hour": 9, "minute": 0, "day_of_week": "mon,fri"}


@pytest.mark.asyncio
async def test_delete_builtin_reminder_rejected(client):
    resp = await client.delete("/api/reminders/morning_summary")
    assert resp.status == 400
    payload = await resp.json()
    assert payload["error"]["code"] == "builtin"


@pytest.mark.asyncio
async def test_delete_missing_reminder_404(client, monkeypatch):
    monkeypatch.setattr(
        "sidekick.services.reminders._remove_reminder",
        lambda scheduler, rid: {"error": "Reminder 'x' not found"},
    )
    resp = await client.delete("/api/reminders/reminder_999")
    assert resp.status == 404
    payload = await resp.json()
    assert payload["error"]["code"] == "not_found"
