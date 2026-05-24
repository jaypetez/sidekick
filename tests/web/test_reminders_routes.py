"""Tests for /reminders routes."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_index_renders_active_reminders(client, bot_data):
    """The list page shows whatever get_all_reminders returns."""
    fake_reminders = [
        {
            "id": "morning_summary",
            "name": "Morning briefing",
            "type": "cron",
            "next_run": "2026-05-24T07:30:00",
            "paused": False,
        },
        {
            "id": "reminder_42",
            "name": "prep lunches",
            "type": "cron",
            "next_run": "2026-05-25T17:00:00",
            "paused": False,
        },
    ]
    with patch("sidekick.web.handlers.reminders.get_all_reminders", return_value=fake_reminders):
        resp = await client.get("/reminders")
    assert resp.status == 200
    body = await resp.text()
    assert "morning_summary" in body
    assert "prep lunches" in body


@pytest.mark.asyncio
async def test_create_calls_add_reminder_with_form_values(client, bot_data):
    with patch("sidekick.web.handlers.reminders.add_reminder") as mock_add:
        mock_add.return_value = {"id": "reminder_99"}
        resp = await client.post(
            "/reminders",
            data={
                "message": "prep lunches",
                "hour": "17",
                "minute": "30",
                "day_of_week": "sun",
                "chat_id": "-100123",
            },
            allow_redirects=False,
        )
    assert resp.status == 303
    assert resp.headers["Location"] == "/reminders"
    mock_add.assert_called_once()
    args = mock_add.call_args.args
    # scheduler, agent, message, hour, minute, chat_id, day_of_week
    assert args[2] == "prep lunches"
    assert args[3] == 17
    assert args[4] == 30
    assert args[5] == -100123
    assert args[6] == "sun"


@pytest.mark.asyncio
async def test_create_rejects_missing_message(client, bot_data):
    resp = await client.post(
        "/reminders",
        data={"message": "", "hour": "9", "minute": "0"},
        allow_redirects=False,
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_create_rejects_non_integer_hour(client, bot_data):
    resp = await client.post(
        "/reminders",
        data={"message": "x", "hour": "abc", "minute": "0"},
        allow_redirects=False,
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_update_pauses_builtin(client, bot_data):
    with patch("sidekick.web.handlers.reminders.update_reminder") as mock_update:
        mock_update.return_value = {"status": "paused", "id": "morning_summary"}
        resp = await client.post(
            "/reminders/morning_summary",
            data={"enabled": "false"},
            allow_redirects=False,
        )
    assert resp.status == 303
    mock_update.assert_called_once()
    # Positional args: scheduler, agent, reminder_id, message, hour, minute, day_of_week, enabled
    args = mock_update.call_args.args
    assert args[2] == "morning_summary"
    assert args[-1] is False


@pytest.mark.asyncio
async def test_update_surfaces_error_as_400(client, bot_data):
    with patch("sidekick.web.handlers.reminders.update_reminder") as mock_update:
        mock_update.return_value = {"error": "Reminder 'bogus' not found"}
        resp = await client.post(
            "/reminders/bogus",
            data={"enabled": "true"},
            allow_redirects=False,
        )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_delete_blocks_builtin(client, bot_data):
    resp = await client.post(
        "/reminders/morning_summary/delete",
        allow_redirects=False,
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_delete_removes_custom(client, bot_data):
    with patch("sidekick.web.handlers.reminders.remove_reminder") as mock_remove:
        mock_remove.return_value = {"status": "removed", "id": "reminder_42"}
        resp = await client.post("/reminders/reminder_42/delete", allow_redirects=False)
    assert resp.status == 303
    mock_remove.assert_called_once()
    assert mock_remove.call_args.args[1] == "reminder_42"


@pytest.mark.asyncio
async def test_delete_404s_when_not_found(client, bot_data):
    with patch("sidekick.web.handlers.reminders.remove_reminder") as mock_remove:
        mock_remove.return_value = {"error": "Reminder 'r_x' not found"}
        resp = await client.post("/reminders/r_x/delete", allow_redirects=False)
    assert resp.status == 404


@pytest.mark.asyncio
async def test_index_503s_when_scheduler_missing(aiohttp_client):
    from sidekick.web import make_app

    app = make_app(bot_data={})
    c = await aiohttp_client(app)
    resp = await c.get("/reminders")
    assert resp.status == 503
