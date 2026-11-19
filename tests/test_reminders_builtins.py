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
    with pytest.raises(ValueError, match="expected a list"):
        reminders._events_from_tool_result([block])


def test_events_from_tool_result_raises_on_error_payload():
    """MCP reports failures as ordinary text; that must not read as 'no events'."""
    block = SimpleNamespace(text='{"error": "Chronary 503"}')
    with pytest.raises(ValueError, match="Chronary 503"):
        reminders._events_from_tool_result([block])


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
async def test_send_morning_summary_shows_local_time_for_utc_events(monkeypatch):
    """Regression: a 6:40 PM Pacific game arrived as 02:40 UTC and the summary
    said "2:40 AM". Times must be shown in the configured timezone."""
    monkeypatch.setenv("TIMEZONE", "America/Los_Angeles")
    bot = MagicMock()
    bot.send_message = AsyncMock()
    session = MagicMock()
    payload = json.dumps(
        [
            {"summary": "Kraken game", "start": "2026-11-20T02:40:00Z"},
            {"summary": "Birthday", "start": "2026-11-19", "all_day": True},
        ]
    )
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(text=payload)])
    )
    await reminders.send_morning_summary(bot, session, "-100123")
    text = bot.send_message.await_args.kwargs["text"]
    assert "Kraken game — 6:40 PM" in text
    assert "2:40 AM" not in text
    assert "Birthday — all day" in text


def test_format_time_converts_to_configured_timezone():
    assert reminders._format_time("2026-11-20T02:40:00Z", "America/Los_Angeles") == "6:40 PM"
    assert reminders._format_time("2026-11-19T18:40:00-08:00", "America/New_York") == "9:40 PM"
    assert reminders._format_time("2026-11-19", "America/Los_Angeles") == "2026-11-19"
    assert reminders._format_time("", "America/Los_Angeles") == "unknown time"


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
    monkeypatch.setattr(reminders, "_reminded_events", {})
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

    monkeypatch.setattr(reminders, "_reminded_events", {})
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


def _events_session(events):
    session = MagicMock()
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(text=json.dumps(events))])
    )
    return session


def _soon(minutes: int = 10) -> str:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    return (datetime.now(ZoneInfo("America/Chicago")) + timedelta(minutes=minutes)).isoformat()


@pytest.mark.asyncio
async def test_failed_fetch_does_not_cause_duplicate_reminders(monkeypatch):
    """Regression: an MCP error payload used to read as [] and prune every
    already-reminded id, so the next good poll re-sent all of them."""
    monkeypatch.setattr(reminders, "_reminded_events", {})
    bot = MagicMock()
    bot.send_message = AsyncMock()
    event = {"id": "e1", "summary": "Standup", "start": _soon()}

    await reminders.send_pre_event_reminders(bot, _events_session([event]), "-1", 30)
    await reminders.send_pre_event_reminders(bot, _events_session({"error": "503"}), "-1", 30)
    await reminders.send_pre_event_reminders(bot, _events_session([event]), "-1", 30)

    assert bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_event_missing_from_truncated_list_is_not_re_reminded(monkeypatch):
    """Dropping out of a (50-capped) result set must not reset the dedupe."""
    monkeypatch.setattr(reminders, "_reminded_events", {})
    bot = MagicMock()
    bot.send_message = AsyncMock()
    event = {"id": "e1", "summary": "Standup", "start": _soon()}

    await reminders.send_pre_event_reminders(bot, _events_session([event]), "-1", 30)
    await reminders.send_pre_event_reminders(bot, _events_session([]), "-1", 30)
    await reminders.send_pre_event_reminders(bot, _events_session([event]), "-1", 30)

    assert bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_rescheduled_event_gets_a_new_reminder(monkeypatch):
    monkeypatch.setattr(reminders, "_reminded_events", {})
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await reminders.send_pre_event_reminders(
        bot, _events_session([{"id": "e1", "summary": "A", "start": _soon(10)}]), "-1", 30
    )
    await reminders.send_pre_event_reminders(
        bot, _events_session([{"id": "e1", "summary": "A", "start": _soon(20)}]), "-1", 30
    )
    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_past_events_are_pruned(monkeypatch):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    past = datetime.now(ZoneInfo("UTC")) - timedelta(hours=1)
    monkeypatch.setattr(reminders, "_reminded_events", {"old@x": past})
    bot = MagicMock()
    bot.send_message = AsyncMock()
    await reminders.send_pre_event_reminders(bot, _events_session([]), "-1", 30)
    assert reminders._reminded_events == {}


@pytest.mark.asyncio
async def test_markdown_title_is_escaped_and_delivered(monkeypatch):
    """A title with _ or * used to be rejected by Telegram (legacy Markdown),
    so the reminder was never sent and retried every 5 minutes."""
    monkeypatch.setattr(reminders, "_reminded_events", {})
    bot = MagicMock()
    bot.send_message = AsyncMock()
    event = {"id": "e1", "summary": "Q3_review *draft*", "start": _soon()}

    await reminders.send_pre_event_reminders(bot, _events_session([event]), "-1", 30)

    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["parse_mode"] == "MarkdownV2"
    assert "Q3\\_review \\*draft\\*" in kwargs["text"]
    assert len(reminders._reminded_events) == 1


@pytest.mark.asyncio
async def test_pre_event_falls_back_to_plain_text(monkeypatch):
    from telegram.error import BadRequest

    monkeypatch.setattr(reminders, "_reminded_events", {})
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=[BadRequest("can't parse entities"), None])
    event = {"id": "e1", "summary": "Weird [title", "start": _soon()}

    await reminders.send_pre_event_reminders(bot, _events_session([event]), "-1", 30)

    assert bot.send_message.await_count == 2
    assert "parse_mode" not in bot.send_message.await_args.kwargs
    assert "Weird [title" in bot.send_message.await_args.kwargs["text"]
    assert len(reminders._reminded_events) == 1


@pytest.mark.asyncio
async def test_untitled_event_does_not_crash(monkeypatch):
    monkeypatch.setattr(reminders, "_reminded_events", {})
    bot = MagicMock()
    bot.send_message = AsyncMock()
    await reminders.send_pre_event_reminders(
        bot, _events_session([{"id": "e1", "start": _soon()}]), "-1", 30
    )
    assert "untitled" in bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_hung_mcp_call_times_out(monkeypatch):
    import asyncio

    monkeypatch.setattr(reminders, "MCP_CALL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(reminders, "_reminded_events", {})

    async def hang(*_a, **_k):
        await asyncio.sleep(10)

    session = MagicMock()
    session.call_tool = hang
    bot = MagicMock()
    bot.send_message = AsyncMock()
    await asyncio.wait_for(reminders.send_pre_event_reminders(bot, session, "-1", 30), 2)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_pre_event_reminders_swallows_mcp_error(monkeypatch):
    monkeypatch.setattr(reminders, "_reminded_events", {})
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


def _live_builtin_scheduler(pre_event_minutes: int = 30):
    """A real (paused) AsyncIOScheduler with both built-in jobs registered."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.start(paused=True)
    scheduler.add_job(
        reminders.send_morning_summary,
        CronTrigger(hour=7, minute=30, timezone="UTC"),
        args=["bot", "mcp", "123"],
        id="morning_summary",
    )
    if pre_event_minutes:
        scheduler.add_job(
            reminders.send_pre_event_reminders,
            IntervalTrigger(minutes=5),
            args=["bot", "mcp", "123", pre_event_minutes],
            id="pre_event_check",
        )
    return scheduler


@pytest.mark.asyncio
async def test_apply_builtin_settings_reschedules_morning_and_lead_time():
    from sidekick import runtime_config

    scheduler = _live_builtin_scheduler()
    try:
        runtime_config.set_value("MORNING_REMINDER_TIME", "06:15")
        runtime_config.set_value("PRE_EVENT_REMINDER_MINUTES", "45")
        assert reminders.apply_builtin_settings(scheduler) == []

        trigger = scheduler.get_job("morning_summary").trigger
        fields = {f.name: str(f) for f in trigger.fields}
        assert (fields["hour"], fields["minute"]) == ("6", "15")
        assert scheduler.get_job("pre_event_check").args[3] == 45
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_apply_builtin_settings_zero_minutes_pauses_then_resumes():
    from sidekick import runtime_config

    scheduler = _live_builtin_scheduler()
    try:
        runtime_config.set_value("PRE_EVENT_REMINDER_MINUTES", "0")
        reminders.apply_builtin_settings(scheduler)
        assert scheduler.get_job("pre_event_check").next_run_time is None

        runtime_config.set_value("PRE_EVENT_REMINDER_MINUTES", "20")
        reminders.apply_builtin_settings(scheduler)
        job = scheduler.get_job("pre_event_check")
        assert job.next_run_time is not None
        assert job.args[3] == 20
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_apply_builtin_settings_reports_unregistered_job():
    """If the check was off at startup there's no job to edit — needs a restart."""
    from sidekick import runtime_config

    scheduler = _live_builtin_scheduler(pre_event_minutes=0)
    try:
        runtime_config.set_value("PRE_EVENT_REMINDER_MINUTES", "15")
        assert reminders.apply_builtin_settings(scheduler) == ["PRE_EVENT_REMINDER_MINUTES"]
    finally:
        scheduler.shutdown(wait=False)
