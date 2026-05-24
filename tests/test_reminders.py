import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sidekick.reminders import (
    _format_time,
    _read_reminders_file,
    _register_job,
    _REMINDER_CHAT_ID,
    _write_reminders_file,
    add_reminder,
    get_all_reminders,
    load_custom_reminders,
    remove_reminder,
    send_custom_reminder,
    send_morning_summary,
    send_pre_event_reminders,
    update_reminder,
)

# -------------------------------------------------------------------
# _format_time
# -------------------------------------------------------------------


def test_format_time_with_datetime():
    assert _format_time("2026-03-24T14:30:00-05:00") == "2:30 PM"


def test_format_time_all_day():
    assert _format_time("2026-03-24") == "2026-03-24"


def test_format_time_empty():
    assert _format_time("") == "unknown time"


def test_format_time_invalid():
    assert _format_time("not-a-date") == "not-a-date"


# -------------------------------------------------------------------
# JSON persistence
# -------------------------------------------------------------------


def test_read_reminders_file_missing(tmp_reminders_file):
    assert _read_reminders_file() == []


def test_read_reminders_file_corrupt(tmp_reminders_file):
    Path(tmp_reminders_file).write_text("{bad json")
    assert _read_reminders_file() == []


def test_write_then_read_roundtrip(tmp_reminders_file):
    data = [{"id": "r1", "message": "test", "schedule": {"type": "cron", "hour": 8, "minute": 0}}]
    _write_reminders_file(data)
    assert _read_reminders_file() == data


# -------------------------------------------------------------------
# add_reminder
# -------------------------------------------------------------------


def test_add_reminder_cron(mock_scheduler, mock_bot, tmp_reminders_file):
    result = add_reminder(
        scheduler=mock_scheduler,
        agent=mock_bot,
        message="Take out trash",
        hour=18,
        minute=0,
        chat_id=-100123,
    )
    assert result["id"].startswith("reminder_")
    assert result["message"] == "Take out trash"
    assert result["schedule"]["type"] == "cron"
    assert result["schedule"]["hour"] == 18
    assert result["schedule"]["minute"] == 0

    # Verify persisted to file
    saved = json.loads(Path(tmp_reminders_file).read_text())
    assert len(saved) == 1
    assert saved[0]["message"] == "Take out trash"

    # Verify scheduler was called
    mock_scheduler.add_job.assert_called_once()


def test_add_reminder_with_day_of_week(mock_scheduler, mock_bot, tmp_reminders_file):
    result = add_reminder(
        scheduler=mock_scheduler,
        agent=mock_bot,
        message="Prep lunches",
        hour=17,
        minute=0,
        chat_id=-100123,
        day_of_week="sun",
    )
    assert result["schedule"]["day_of_week"] == "sun"


# -------------------------------------------------------------------
# remove_reminder
# -------------------------------------------------------------------


def test_remove_reminder_success(mock_scheduler, mock_bot, tmp_reminders_file):
    added = add_reminder(
        scheduler=mock_scheduler,
        agent=mock_bot,
        message="Test",
        hour=9,
        minute=0,
        chat_id=-100,
    )
    result = remove_reminder(mock_scheduler, added["id"])
    assert result["status"] == "removed"

    saved = json.loads(Path(tmp_reminders_file).read_text())
    assert len(saved) == 0


def test_remove_reminder_builtin_rejected(mock_scheduler):
    result = remove_reminder(mock_scheduler, "morning_summary")
    assert "error" in result
    assert "Cannot remove" in result["error"]


def test_remove_reminder_not_found(mock_scheduler, tmp_reminders_file):
    result = remove_reminder(mock_scheduler, "nonexistent_id")
    assert "error" in result


# -------------------------------------------------------------------
# update_reminder
# -------------------------------------------------------------------


def test_update_reminder_custom(mock_scheduler, mock_bot, tmp_reminders_file):
    added = add_reminder(
        scheduler=mock_scheduler,
        agent=mock_bot,
        message="Old message",
        hour=9,
        minute=0,
        chat_id=-100,
    )
    mock_scheduler.reset_mock()

    result = update_reminder(
        scheduler=mock_scheduler,
        agent=mock_bot,
        reminder_id=added["id"],
        message="New message",
        hour=10,
    )
    assert result["status"] == "updated"

    saved = json.loads(Path(tmp_reminders_file).read_text())
    assert saved[0]["message"] == "New message"
    assert saved[0]["schedule"]["hour"] == 10


def test_update_reminder_not_found(mock_scheduler, mock_bot, tmp_reminders_file):
    result = update_reminder(
        scheduler=mock_scheduler,
        agent=mock_bot,
        reminder_id="nonexistent",
    )
    assert "error" in result


# -------------------------------------------------------------------
# get_all_reminders
# -------------------------------------------------------------------


def test_get_all_reminders_empty(mock_scheduler, tmp_reminders_file):
    result = get_all_reminders(mock_scheduler)
    assert result == []


# -------------------------------------------------------------------
# send_custom_reminder
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_custom_reminder_processes_through_agent(monkeypatch):
    """Verify send_custom_reminder routes message through agent and sends response."""
    monkeypatch.setenv("REMINDER_CHAT_ID", "-100999")
    agent = MagicMock()
    agent.process_message = AsyncMock(return_value="You have 3 events today.")
    agent.bot = MagicMock()
    agent.bot.send_message = AsyncMock()

    await send_custom_reminder(agent, "What's on the calendar today?")

    agent.process_message.assert_called_once_with(
        _REMINDER_CHAT_ID, "What's on the calendar today?"
    )
    agent.bot.send_message.assert_called_once_with(
        chat_id=-100999, text="You have 3 events today.", parse_mode="Markdown"
    )
    agent.clear_history.assert_called_once_with(_REMINDER_CHAT_ID)


@pytest.mark.asyncio
async def test_send_custom_reminder_no_chat_id(monkeypatch):
    """If REMINDER_CHAT_ID is unset, send_custom_reminder should not call agent."""
    monkeypatch.delenv("REMINDER_CHAT_ID", raising=False)
    agent = MagicMock()
    agent.process_message = AsyncMock()

    await send_custom_reminder(agent, "Test")

    agent.process_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_custom_reminder_falls_back_on_agent_error(monkeypatch):
    """If agent.process_message raises, fall back to sending raw message."""
    monkeypatch.setenv("REMINDER_CHAT_ID", "-100999")
    agent = MagicMock()
    agent.process_message = AsyncMock(side_effect=Exception("API error"))
    agent.bot = MagicMock()
    agent.bot.send_message = AsyncMock()

    await send_custom_reminder(agent, "Take out the trash")

    # Should fall back to raw message
    agent.bot.send_message.assert_called_once_with(
        chat_id=-100999, text="Reminder: Take out the trash"
    )


# -------------------------------------------------------------------
# _register_job — verify scheduler.add_job is called correctly
# -------------------------------------------------------------------


def test_register_job_cron():
    """Verify _register_job creates a CronTrigger job with correct args."""
    scheduler = MagicMock()
    agent = MagicMock()
    reminder = {
        "id": "reminder_123",
        "chat_id": -100999,
        "message": "Test cron",
        "schedule": {"type": "cron", "hour": 17, "minute": 30, "day_of_week": "mon,fri"},
    }
    _register_job(scheduler, agent, reminder, "America/Chicago")

    scheduler.add_job.assert_called_once()
    call_kwargs = scheduler.add_job.call_args
    # Function should be send_custom_reminder
    assert call_kwargs[0][0] is send_custom_reminder
    # Args should be [agent, message] (no chat_id — read from env at send time)
    assert call_kwargs[1]["args"] == [agent, "Test cron"]
    assert call_kwargs[1]["id"] == "reminder_123"


def test_register_job_interval():
    """Verify _register_job creates an IntervalTrigger job."""
    scheduler = MagicMock()
    agent = MagicMock()
    reminder = {
        "id": "reminder_456",
        "chat_id": -100999,
        "message": "Test interval",
        "schedule": {"type": "interval", "interval_minutes": 15},
    }
    _register_job(scheduler, agent, reminder, "America/Chicago")

    scheduler.add_job.assert_called_once()
    assert scheduler.add_job.call_args[1]["args"] == [agent, "Test interval"]


# -------------------------------------------------------------------
# load_custom_reminders
# -------------------------------------------------------------------


def test_load_custom_reminders_restores_jobs(tmp_reminders_file):
    """Verify load_custom_reminders reads JSON and registers each enabled reminder."""
    reminders = [
        {
            "id": "r1",
            "chat_id": -100,
            "message": "First",
            "schedule": {"type": "cron", "hour": 8, "minute": 0},
            "enabled": True,
        },
        {
            "id": "r2",
            "chat_id": -100,
            "message": "Disabled",
            "schedule": {"type": "cron", "hour": 9, "minute": 0},
            "enabled": False,
        },
        {
            "id": "r3",
            "chat_id": -100,
            "message": "Third",
            "schedule": {"type": "cron", "hour": 10, "minute": 0},
            "enabled": True,
        },
    ]
    Path(tmp_reminders_file).write_text(json.dumps(reminders))

    scheduler = MagicMock()
    agent = MagicMock()
    load_custom_reminders(scheduler, agent)

    # Only 2 enabled reminders should be registered
    assert scheduler.add_job.call_count == 2


# -------------------------------------------------------------------
# Scheduler integration — real AsyncIOScheduler fires a job
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_actually_fires_reminder(monkeypatch):
    """End-to-end: real scheduler fires send_custom_reminder within seconds."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    monkeypatch.setenv("REMINDER_CHAT_ID", "-100999")

    agent = MagicMock()
    agent.process_message = AsyncMock(return_value="Reminder response")
    agent.bot = MagicMock()
    agent.bot.send_message = AsyncMock()

    scheduler = AsyncIOScheduler(timezone="America/Chicago")
    scheduler.add_job(
        send_custom_reminder,
        IntervalTrigger(seconds=1),
        args=[agent, "Scheduler test"],
        id="test_fire",
        misfire_grace_time=10,
    )
    scheduler.start()

    # Wait up to 3 seconds for the job to fire
    for _ in range(30):
        if agent.bot.send_message.call_count > 0:
            break
        await asyncio.sleep(0.1)

    scheduler.shutdown(wait=False)

    assert agent.bot.send_message.call_count >= 1
    agent.process_message.assert_called_with(_REMINDER_CHAT_ID, "Scheduler test")


# -------------------------------------------------------------------
# Timezone-aware date handling in built-in reminders
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_morning_summary_uses_configured_timezone(monkeypatch):
    """Verify send_morning_summary uses TIMEZONE env var, not system time."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Set timezone to one where the date differs from UTC
    # Simulate: UTC is April 2 at 05:00, but in Honolulu (UTC-10) it's still April 1
    fake_now = datetime(2026, 4, 2, 5, 0, 0, tzinfo=ZoneInfo("UTC"))

    monkeypatch.setenv("TIMEZONE", "Pacific/Honolulu")

    original_now = datetime.now

    def patched_now(tz=None):
        if tz is not None:
            return fake_now.astimezone(tz)
        return original_now(tz)

    monkeypatch.setattr(
        "sidekick.reminders.datetime",
        type(
            "dt",
            (),
            {
                "now": staticmethod(patched_now),
                "fromisoformat": datetime.fromisoformat,
                "strptime": datetime.strptime,
            },
        ),
    )

    bot = MagicMock()
    bot.send_message = AsyncMock()
    mcp_session = MagicMock()
    mcp_result = MagicMock()
    mcp_result.content = [MagicMock(text="[]")]
    mcp_session.call_tool = AsyncMock(return_value=mcp_result)

    await send_morning_summary(bot, mcp_session, "-100999")

    # Should query April 1 (Honolulu date), not April 2 (UTC date)
    mcp_session.call_tool.assert_called_once_with(
        "list_events", {"start_date": "2026-04-01", "end_date": "2026-04-01"}
    )


@pytest.mark.asyncio
async def test_pre_event_check_uses_configured_timezone(monkeypatch):
    """Verify send_pre_event_reminders uses TIMEZONE env var, not UTC."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    fake_now = datetime(2026, 4, 2, 5, 0, 0, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setenv("TIMEZONE", "Pacific/Honolulu")

    original_now = datetime.now

    def patched_now(tz=None):
        if tz is not None:
            return fake_now.astimezone(tz)
        return original_now(tz)

    monkeypatch.setattr(
        "sidekick.reminders.datetime",
        type(
            "dt",
            (),
            {
                "now": staticmethod(patched_now),
                "fromisoformat": datetime.fromisoformat,
                "strptime": datetime.strptime,
            },
        ),
    )

    bot = MagicMock()
    bot.send_message = AsyncMock()
    mcp_session = MagicMock()
    mcp_result = MagicMock()
    mcp_result.content = [MagicMock(text="[]")]
    mcp_session.call_tool = AsyncMock(return_value=mcp_result)

    await send_pre_event_reminders(bot, mcp_session, "-100999", 30)

    # Should query April 1 (Honolulu date), not April 2 (UTC date)
    mcp_session.call_tool.assert_called_once_with(
        "list_events",
        {"start_date": "2026-04-01", "end_date": "2026-04-01", "max_results": 50},
    )
