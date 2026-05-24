"""Schema validation for reminders.json — bad entries are dropped, not fatal."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

from sidekick.reminders import _validate_reminder, load_custom_reminders


def test_validate_reminder_accepts_valid_cron():
    payload = {
        "id": "r1",
        "message": "hello",
        "schedule": {"type": "cron", "hour": 8, "minute": 30},
    }
    out = _validate_reminder(payload)
    assert out is not None
    assert out["id"] == "r1"


def test_validate_reminder_rejects_missing_key(caplog):
    with caplog.at_level(logging.WARNING):
        out = _validate_reminder({"id": "r1", "message": "no schedule"})
    assert out is None
    assert any("missing required keys" in r.message for r in caplog.records)


def test_validate_reminder_rejects_wrong_type(caplog):
    with caplog.at_level(logging.WARNING):
        out = _validate_reminder(
            {"id": "r1", "message": 123, "schedule": {"type": "cron", "hour": 8, "minute": 0}}
        )
    assert out is None


def test_validate_reminder_strips_unknown_keys(caplog):
    payload = {
        "id": "r1",
        "message": "hi",
        "schedule": {"type": "cron", "hour": 8, "minute": 0},
        "evil": "drop me",
    }
    with caplog.at_level(logging.WARNING):
        out = _validate_reminder(payload)
    assert out is not None
    assert "evil" not in out
    assert any("unknown keys" in r.message for r in caplog.records)


def test_load_custom_reminders_drops_invalid_and_keeps_valid(tmp_reminders_file, caplog):
    """Mix of valid + invalid entries → only valid one is registered, no exceptions."""
    reminders = [
        {  # valid
            "id": "good",
            "message": "valid one",
            "schedule": {"type": "cron", "hour": 8, "minute": 0},
            "enabled": True,
        },
        {  # invalid: missing schedule
            "id": "bad1",
            "message": "no schedule",
        },
        {  # invalid: wrong type for message
            "id": "bad2",
            "message": 42,
            "schedule": {"type": "cron", "hour": 9, "minute": 0},
        },
        {  # valid but has unknown keys — should still register
            "id": "good_extra",
            "message": "with extras",
            "schedule": {"type": "cron", "hour": 10, "minute": 0},
            "enabled": True,
            "mystery_field": "should be dropped",
        },
    ]
    Path(tmp_reminders_file).write_text(json.dumps(reminders))

    scheduler = MagicMock()
    agent = MagicMock()

    with caplog.at_level(logging.WARNING):
        # Must not raise
        load_custom_reminders(scheduler, agent)

    # Two valid entries registered
    assert scheduler.add_job.call_count == 2
    # Warnings logged for the two bad ones
    warning_text = " ".join(r.message for r in caplog.records)
    assert "missing required keys" in warning_text or "bad1" in warning_text
