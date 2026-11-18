"""Reliability of custom-reminder persistence and mutation.

Regression tests for: truncated/corrupt reminders.json being silently
overwritten, lost updates between the chat and web threads, same-second id
collisions, an invalid edit deleting the reminder, and substring "remove".
"""

from __future__ import annotations

import json
import stat
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from sidekick import reminders


@pytest.fixture
def scheduler():
    """A real scheduler (paused) so trigger validation and job state are real."""
    sched = BackgroundScheduler(timezone="UTC")
    sched.start(paused=True)
    yield sched
    sched.shutdown(wait=False)


def _saved(path: str) -> list[dict]:
    return json.loads(Path(path).read_text())


# --- file safety -------------------------------------------------------------


def test_corrupt_file_is_quarantined_not_overwritten(tmp_reminders_file, scheduler):
    Path(tmp_reminders_file).write_text('[{"id": "reminder_old", "message": "kee')  # truncated

    reminders.add_reminder(scheduler, MagicMock(), "new one", 9, 0, chat_id=1)

    quarantined = list(Path(tmp_reminders_file).parent.glob("reminders.json.corrupt-*"))
    assert len(quarantined) == 1
    assert "reminder_old" in quarantined[0].read_text()  # original bytes preserved
    assert [r["message"] for r in _saved(tmp_reminders_file)] == ["new one"]


def test_unreadable_file_raises_instead_of_returning_empty(tmp_reminders_file, monkeypatch):
    Path(tmp_reminders_file).write_text("[]")

    def boom(*_a, **_k):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", boom)
    with pytest.raises(reminders.RemindersFileError):
        reminders._read_reminders_file()


def test_write_is_atomic_and_leaves_no_temp_files(tmp_reminders_file):
    reminders._write_reminders_file([{"id": "a"}])
    reminders._write_reminders_file([{"id": "b"}])
    names = sorted(p.name for p in Path(tmp_reminders_file).parent.iterdir())
    assert names == ["reminders.json"]
    assert _saved(tmp_reminders_file) == [{"id": "b"}]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_written_file_is_private(tmp_reminders_file):
    reminders._write_reminders_file([])
    assert stat.S_IMODE(Path(tmp_reminders_file).stat().st_mode) == 0o600


def test_concurrent_adds_from_threads_are_not_lost(tmp_reminders_file, scheduler):
    """The web dashboard writes from executor threads while chat tools write
    on the loop; read-modify-write must be serialized."""
    agent = MagicMock()
    threads = [
        threading.Thread(target=reminders.add_reminder, args=(scheduler, agent, f"r{i}", 8, i, 1))
        for i in range(25)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    saved = _saved(tmp_reminders_file)
    assert sorted(r["message"] for r in saved) == sorted(f"r{i}" for i in range(25))
    assert len({r["id"] for r in saved}) == 25


# --- ids & validation ----------------------------------------------------------


def test_ids_unique_within_the_same_second(tmp_reminders_file, scheduler):
    agent = MagicMock()
    a = reminders.add_reminder(scheduler, agent, "8am", 8, 0, chat_id=1)
    b = reminders.add_reminder(scheduler, agent, "5pm", 17, 0, chat_id=1)
    assert a["id"] != b["id"]
    assert {j.id for j in scheduler.get_jobs()} == {a["id"], b["id"]}


@pytest.mark.parametrize(
    ("hour", "minute", "dow"), [(25, 0, None), (8, 60, None), (-1, 0, None), (8, 0, "weekdays")]
)
def test_add_rejects_invalid_schedule_and_saves_nothing(
    tmp_reminders_file, scheduler, hour, minute, dow
):
    with pytest.raises(ValueError):
        reminders.add_reminder(scheduler, MagicMock(), "x", hour, minute, 1, day_of_week=dow)
    assert not Path(tmp_reminders_file).exists()
    assert scheduler.get_jobs() == []


def test_load_skips_out_of_range_entries(tmp_reminders_file, scheduler):
    Path(tmp_reminders_file).write_text(
        json.dumps(
            [
                {"id": "ok", "message": "m", "schedule": {"type": "cron", "hour": 7, "minute": 0}},
                {
                    "id": "bad",
                    "message": "m",
                    "schedule": {"type": "cron", "hour": 31, "minute": 0},
                },
            ]
        )
    )
    reminders.load_custom_reminders(scheduler, MagicMock())
    assert [j.id for j in scheduler.get_jobs()] == ["ok"]


# --- update ----------------------------------------------------------------------


def test_invalid_update_leaves_reminder_intact(tmp_reminders_file, scheduler):
    """Regression: the old code saved the change and removed the job *before*
    building the new trigger, so a bad hour deleted the reminder."""
    created = reminders.add_reminder(scheduler, MagicMock(), "standup", 9, 30, chat_id=1)

    with pytest.raises(ValueError):
        reminders.update_reminder(scheduler, MagicMock(), created["id"], hour=25)

    assert _saved(tmp_reminders_file)[0]["schedule"]["hour"] == 9
    assert scheduler.get_job(created["id"]) is not None


def test_update_reschedules_live_job(tmp_reminders_file, scheduler):
    created = reminders.add_reminder(scheduler, MagicMock(), "standup", 9, 30, chat_id=1)
    reminders.update_reminder(scheduler, MagicMock(), created["id"], hour=10)
    fields = {f.name: str(f) for f in scheduler.get_job(created["id"]).trigger.fields}
    assert fields["hour"] == "10"


def test_update_disable_removes_job_but_keeps_entry(tmp_reminders_file, scheduler):
    created = reminders.add_reminder(scheduler, MagicMock(), "standup", 9, 30, chat_id=1)
    reminders.update_reminder(scheduler, MagicMock(), created["id"], enabled=False)
    assert scheduler.get_job(created["id"]) is None
    assert _saved(tmp_reminders_file)[0]["enabled"] is False


def test_update_builtin_interval_job_rejects_time_of_day(scheduler):
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler.add_job(lambda: None, IntervalTrigger(minutes=5), id="pre_event_check")
    with pytest.raises(ValueError, match="interval"):
        reminders.update_reminder(scheduler, MagicMock(), "pre_event_check", hour=8)
    assert isinstance(scheduler.get_job("pre_event_check").trigger, IntervalTrigger)


def test_update_builtin_cron_job_changes_time(scheduler):
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(lambda: None, CronTrigger(hour=7, minute=30), id="morning_summary")
    reminders.update_reminder(scheduler, MagicMock(), "morning_summary", minute=45)
    fields = {f.name: str(f) for f in scheduler.get_job("morning_summary").trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("7", "45")


# --- remove ------------------------------------------------------------------------


def test_remove_requires_exact_id(tmp_reminders_file, scheduler):
    """Regression: "a" used to fuzzy-match the first message containing "a"."""
    created = reminders.add_reminder(scheduler, MagicMock(), "water the plants", 9, 0, chat_id=1)
    result = reminders.remove_reminder(scheduler, "a")
    assert "error" in result
    assert len(_saved(tmp_reminders_file)) == 1

    assert reminders.remove_reminder(scheduler, created["id"])["status"] == "removed"
    assert _saved(tmp_reminders_file) == []
    assert scheduler.get_job(created["id"]) is None
