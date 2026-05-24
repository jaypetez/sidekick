"""Tests for the built-in reminder functions: setup_scheduler, send_morning_summary,
send_pre_event_reminders, and the JSON event parsing helper.

These complement test_reminders.py (which focuses on custom-reminder CRUD)."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sidekick import reminders

# -------------------------------------------------------------------
# setup_scheduler
# -------------------------------------------------------------------


def test_setup_scheduler_no_reminder_chat_id_skips_jobs(monkeypatch):
    """Without REMINDER_CHAT_ID, no built-in jobs should be scheduled."""
    monkeypatch.delenv("REMINDER_CHAT_ID", raising=False)
    fake_scheduler = MagicMock()
    with patch("sidekick.reminders.AsyncIOScheduler", return_value=fake_scheduler) as scheduler_cls:
        result = reminders.setup_scheduler(MagicMock(), MagicMock())

    scheduler_cls.assert_called_once()
    fake_scheduler.add_job.assert_not_called()
    fake_scheduler.start.assert_called_once()
    assert result is fake_scheduler


def test_setup_scheduler_with_chat_id_schedules_both_jobs(monkeypatch):
    """With chat id set, morning_summary + pre_event_check should both register."""
    monkeypatch.setenv("REMINDER_CHAT_ID", "-100123")
    monkeypatch.setenv("MORNING_REMINDER_TIME", "08:15")
    monkeypatch.setenv("PRE_EVENT_REMINDER_MINUTES", "20")
    fake_scheduler = MagicMock()
    with patch("sidekick.reminders.AsyncIOScheduler", return_value=fake_scheduler):
        reminders.setup_scheduler(MagicMock(), MagicMock())

    job_ids = {call.kwargs["id"] for call in fake_scheduler.add_job.call_args_list}
    assert job_ids == {"morning_summary", "pre_event_check"}


def test_setup_scheduler_pre_event_minutes_zero_disables_check(monkeypatch):
    """PRE_EVENT_REMINDER_MINUTES=0 turns off the pre-event check job."""
    monkeypatch.setenv("REMINDER_CHAT_ID", "-100123")
    monkeypatch.setenv("PRE_EVENT_REMINDER_MINUTES", "0")
    fake_scheduler = MagicMock()
    with patch("sidekick.reminders.AsyncIOScheduler", return_value=fake_scheduler):
        reminders.setup_scheduler(MagicMock(), MagicMock())

    job_ids = {call.kwargs["id"] for call in fake_scheduler.add_job.call_args_list}
    assert job_ids == {"morning_summary"}


def test_setup_scheduler_skips_builtins_when_bot_is_none(monkeypatch):
    """Web-only mode: no Telegram Bot → built-in delivery jobs cannot run, so skip them."""
    monkeypatch.setenv("REMINDER_CHAT_ID", "-100123")  # would normally enable jobs
    monkeypatch.setenv("PRE_EVENT_REMINDER_MINUTES", "30")
    fake_scheduler = MagicMock()
    with patch("sidekick.reminders.AsyncIOScheduler", return_value=fake_scheduler):
        result = reminders.setup_scheduler(None, MagicMock())

    fake_scheduler.add_job.assert_not_called()
    fake_scheduler.start.assert_called_once()
    assert result is fake_scheduler


# -------------------------------------------------------------------
# _events_from_tool_result helper
# -------------------------------------------------------------------


def test_events_from_tool_result_empty_content():
    assert reminders._events_from_tool_result([]) == []


def test_events_from_tool_result_no_text_attr():
    assert reminders._events_from_tool_result([SimpleNamespace()]) == []


def test_events_from_tool_result_parses_json_list():
    block = SimpleNamespace(text='[{"id": "e1", "summary": "Dentist"}]')
    assert reminders._events_from_tool_result([block]) == [{"id": "e1", "summary": "Dentist"}]


def test_events_from_tool_result_rejects_non_list_payload():
    block = SimpleNamespace(text='{"id": "e1"}')
    assert reminders._events_from_tool_result([block]) == []


# -------------------------------------------------------------------
# send_morning_summary
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_morning_summary_no_events_sends_brief():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    session = MagicMock()
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(text="[]")])
    )
    await reminders.send_morning_summary(bot, session, "-100123")
    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.kwargs["text"]
    assert "No events" in text


@pytest.mark.asyncio
async def test_send_morning_summary_with_events_lists_them():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    session = MagicMock()
    payload = json.dumps(
        [
            {"summary": "Dentist", "start": "2026-05-23T09:00:00-05:00"},
            {"summary": "Lunch", "start": "2026-05-23T12:30:00-05:00"},
        ]
    )
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(text=payload)])
    )
    await reminders.send_morning_summary(bot, session, "-100123")
    text = bot.send_message.await_args.kwargs["text"]
    assert "Dentist" in text
    assert "Lunch" in text


@pytest.mark.asyncio
async def test_send_morning_summary_swallows_mcp_failure():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    session = MagicMock()
    session.call_tool = AsyncMock(side_effect=RuntimeError("mcp down"))
    await reminders.send_morning_summary(bot, session, "-100123")
    # Failure path: log + return; no message sent.
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_morning_summary_swallows_send_failure():
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))
    session = MagicMock()
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(text="[]")])
    )
    # Should not raise.
    await reminders.send_morning_summary(bot, session, "-100123")


# -------------------------------------------------------------------
# send_pre_event_reminders
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_pre_event_reminders_skips_all_day_events(monkeypatch):
    """Events without 'T' in their start are all-day; must not generate alerts."""
    monkeypatch.setattr(reminders, "_reminded_event_ids", set())
    bot = MagicMock()
    bot.send_message = AsyncMock()
    session = MagicMock()
    payload = json.dumps([{"id": "e1", "summary": "Holiday", "start": "2026-05-23"}])
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(text=payload)])
    )
    await reminders.send_pre_event_reminders(bot, session, "-100123", 30)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_pre_event_reminders_dedupes_same_event(monkeypatch):
    """Each event id should only trigger one alert."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(reminders, "_reminded_event_ids", set())
    tz = ZoneInfo("America/Chicago")
    # Schedule the event 10 minutes from "now".
    upcoming = (datetime.now(tz) + timedelta(minutes=10)).isoformat()

    bot = MagicMock()
    bot.send_message = AsyncMock()
    session = MagicMock()
    payload = json.dumps([{"id": "e42", "summary": "Standup", "start": upcoming}])
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(text=payload)])
    )

    await reminders.send_pre_event_reminders(bot, session, "-100123", 30)
    await reminders.send_pre_event_reminders(bot, session, "-100123", 30)

    # Sent exactly once despite two calls.
    assert bot.send_message.await_count == 1
    assert "Standup" in bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_send_pre_event_reminders_swallows_mcp_error(monkeypatch):
    monkeypatch.setattr(reminders, "_reminded_event_ids", set())
    bot = MagicMock()
    bot.send_message = AsyncMock()
    session = MagicMock()
    session.call_tool = AsyncMock(side_effect=RuntimeError("mcp down"))
    await reminders.send_pre_event_reminders(bot, session, "-100123", 30)
    bot.send_message.assert_not_awaited()


# -------------------------------------------------------------------
# _format_time
# -------------------------------------------------------------------


def test_format_time_handles_iso():
    out = reminders._format_time("2026-05-23T09:00:00-05:00")
    assert "9:00" in out


def test_format_time_passthrough_for_all_day():
    assert reminders._format_time("2026-05-23") == "2026-05-23"


def test_format_time_empty():
    assert reminders._format_time("") == "unknown time"


def test_format_time_malformed_iso_returns_raw():
    assert reminders._format_time("not-a-date") == "not-a-date"
