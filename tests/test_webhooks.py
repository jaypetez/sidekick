"""Unit tests for sidekick.webhooks (verify, parse, format, dedupe)."""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime

import pytest
from chronary import SignatureVerificationError

from sidekick import webhooks
from sidekick.webhooks import DeliveryLog, InvalidPayload, format_reminder, parse_reminder

from .webhook_helpers import CALENDAR_ID, SECRET, reminder_payload, signed


def _parse(body, headers, *, calendar_id=CALENDAR_ID):
    return parse_reminder(body, headers, secret=SECRET, calendar_id=calendar_id)


def test_valid_reminder_parses():
    notice = _parse(*signed(reminder_payload()))
    assert notice is not None
    assert notice.delivery_id == "whd_1"
    assert notice.event_id == "evt_1"
    assert notice.title == "Strategy sync"
    assert notice.start_time == datetime(2026, 4, 17, 14, 0, tzinfo=UTC)
    assert notice.reminder_minutes == 10
    assert notice.is_test is False


def test_bad_signature_rejected():
    body, headers = signed(reminder_payload(), secret="whsec_attacker")
    with pytest.raises(SignatureVerificationError):
        _parse(body, headers)


def test_tampered_body_rejected():
    body, headers = signed(reminder_payload())
    with pytest.raises(SignatureVerificationError):
        _parse(body.replace(b"Strategy", b"Phishing"), headers)


def test_stale_timestamp_rejected():
    body, headers = signed(reminder_payload(), timestamp=int(time.time()) - 3600)
    with pytest.raises(SignatureVerificationError):
        _parse(body, headers)


def test_missing_signature_rejected():
    body, headers = signed(reminder_payload())
    del headers["X-Signature"]
    with pytest.raises(SignatureVerificationError):
        _parse(body, headers)


def test_other_event_types_ignored():
    assert _parse(*signed(reminder_payload(), event_type="event.created")) is None


def test_other_calendar_in_org_ignored():
    assert _parse(*signed(reminder_payload(calendar_id="cal_someone_else"))) is None


def test_calendar_filter_skipped_when_unconfigured():
    notice = _parse(*signed(reminder_payload(calendar_id="cal_x")), calendar_id=None)
    assert notice is not None


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[1, 2]",
        b'{"calendar_id": "cal_ours"}',
        b'{"event_id": "e", "start_time": "soon"}',
    ],
)
def test_signed_but_unusable_payloads_raise(body):
    with pytest.raises(InvalidPayload):
        _parse(*signed(body))


def test_missing_delivery_id_derives_stable_per_offset_key():
    a = _parse(*signed(reminder_payload(reminder_minutes=10), delivery_id=None))
    b = _parse(*signed(reminder_payload(reminder_minutes=10), delivery_id=None))
    c = _parse(*signed(reminder_payload(reminder_minutes=1440), delivery_id=None))
    assert a and b and c
    assert a.delivery_id == b.delivery_id != c.delivery_id


def test_test_header_flagged():
    notice = _parse(*signed(reminder_payload(), test=True))
    assert notice is not None and notice.is_test


def test_blank_title_becomes_untitled():
    notice = _parse(*signed(reminder_payload(title="  ")))
    assert notice is not None and notice.title == "(untitled)"


# --- format_reminder ---------------------------------------------------------------


def _notice(**overrides):
    payload = reminder_payload(**overrides)
    notice = _parse(*signed(payload))
    assert notice is not None
    return notice


def test_format_converts_to_local_time_same_day():
    now = datetime(2026, 4, 17, 13, 50, tzinfo=UTC)
    v2, plain = format_reminder(_notice(), "America/Chicago", now=now)
    assert plain == "⏰ Strategy sync starts in 10 minutes (9:00 AM)"
    assert "*Strategy sync*" in v2
    assert "\\(9:00 AM\\)" in v2


def test_format_other_day_includes_date_and_day_lead():
    now = datetime(2026, 4, 16, 14, 0, tzinfo=UTC)
    _, plain = format_reminder(_notice(reminder_minutes=1440), "UTC", now=now)
    assert plain == "⏰ Strategy sync starts tomorrow (Fri Apr 17, 2:00 PM)"


@pytest.mark.parametrize(
    ("minutes", "phrase"),
    [
        (1, "in 1 minute"),
        (45, "in 45 minutes"),
        (60, "in 1 hour"),
        (120, "in 2 hours"),
        (90, "in 90 minutes"),
        (2880, "in 2 days"),
    ],
)
def test_lead_time_phrases(minutes, phrase):
    now = datetime(2026, 4, 17, 0, 0, tzinfo=UTC)
    _, plain = format_reminder(_notice(reminder_minutes=minutes), "UTC", now=now)
    assert phrase in plain


def test_format_escapes_markdown_in_title_and_marks_tests():
    notice = _parse(*signed(reminder_payload(title="Q3_review *draft*"), test=True))
    assert notice is not None
    v2, plain = format_reminder(notice, "UTC", now=datetime(2026, 4, 17, tzinfo=UTC))
    assert "Q3\\_review \\*draft\\*" in v2
    assert plain.startswith("[test] ")
    assert v2.startswith("\\[test\\] ")


# --- DeliveryLog ---------------------------------------------------------------------


def test_delivery_log_dedupes():
    log = DeliveryLog(conn=sqlite3.connect(":memory:", check_same_thread=False))
    assert log.record("whd_1") is True
    assert log.record("whd_1") is False
    assert log.record("whd_2") is True


def test_delivery_log_survives_restart(tmp_path):
    db = str(tmp_path / "s.db")
    assert DeliveryLog(db).record("whd_1") is True
    assert DeliveryLog(db).record("whd_1") is False


def test_delivery_log_prunes_old_ids(monkeypatch):
    log = DeliveryLog(conn=sqlite3.connect(":memory:", check_same_thread=False))
    clock = [1_000_000.0]
    monkeypatch.setattr(webhooks.time, "time", lambda: clock[0])
    log.record("old")
    clock[0] += webhooks.DELIVERY_RETENTION_SECONDS + 1
    log.record("new")
    rows = log._conn.execute("SELECT delivery_id FROM webhook_deliveries").fetchall()
    assert [r[0] for r in rows] == ["new"]


def test_helper_signature_matches_sdk_signer():
    """Guard against the test helper drifting from Chronary's real scheme."""
    from chronary.webhook import _compute_signature

    body, headers = signed(reminder_payload())
    expected = _compute_signature(SECRET, headers["X-Timestamp"], body)
    assert headers["X-Signature"] == expected
