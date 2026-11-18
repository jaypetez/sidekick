"""PRE_EVENT_SOURCE switches pre-event reminders between polling and webhooks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sidekick import reminders, runtime_config


def _setup(monkeypatch, source: str | None):
    monkeypatch.setenv("REMINDER_CHAT_ID", "-100123")
    monkeypatch.setenv("PRE_EVENT_REMINDER_MINUTES", "20")
    if source is None:
        monkeypatch.delenv("PRE_EVENT_SOURCE", raising=False)
    else:
        monkeypatch.setenv("PRE_EVENT_SOURCE", source)
    fake = MagicMock()
    with patch("sidekick.reminders.AsyncIOScheduler", return_value=fake):
        reminders.setup_scheduler(MagicMock(), MagicMock())
    return {c.kwargs["id"]: c.kwargs for c in fake.add_job.call_args_list}


def test_default_source_polls(monkeypatch):
    jobs = _setup(monkeypatch, None)
    assert "next_run_time" not in jobs["pre_event_check"]


def test_webhook_source_registers_check_paused(monkeypatch):
    jobs = _setup(monkeypatch, "webhook")
    assert jobs["pre_event_check"]["next_run_time"] is None
    assert "next_run_time" not in jobs["morning_summary"]


@pytest.mark.parametrize(("value", "ok"), [("poll", True), ("Webhook", True), ("push", False)])
def test_source_validation(value, ok):
    if ok:
        runtime_config.set_value("PRE_EVENT_SOURCE", value)
        assert runtime_config.pre_event_source() == value.lower()
    else:
        with pytest.raises(runtime_config.ConfigError):
            runtime_config.set_value("PRE_EVENT_SOURCE", value)


def test_garbage_env_value_falls_back_to_poll(monkeypatch):
    monkeypatch.setenv("PRE_EVENT_SOURCE", "carrier-pigeon")
    assert runtime_config.pre_event_source() == "poll"


@pytest.mark.asyncio
async def test_switching_source_live_pauses_and_resumes():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.start(paused=True)
    try:
        scheduler.add_job(
            reminders.send_pre_event_reminders,
            IntervalTrigger(minutes=5),
            args=["bot", "mcp", "1", 30],
            id="pre_event_check",
        )
        runtime_config.set_value("PRE_EVENT_SOURCE", "webhook")
        reminders.apply_builtin_settings(scheduler)
        assert scheduler.get_job("pre_event_check").next_run_time is None

        runtime_config.set_value("PRE_EVENT_SOURCE", "poll")
        reminders.apply_builtin_settings(scheduler)
        assert scheduler.get_job("pre_event_check").next_run_time is not None
    finally:
        scheduler.shutdown(wait=False)


def test_webhook_secret_is_redacted_but_not_editable():
    assert "CHRONARY_WEBHOOK_SECRET" in runtime_config.SECRET_KEYS
    assert "CHRONARY_WEBHOOK_SECRET" not in runtime_config.EDITABLE_KEYS
    with pytest.raises(runtime_config.ConfigError):
        runtime_config.set_value("CHRONARY_WEBHOOK_SECRET", "whsec_x")
