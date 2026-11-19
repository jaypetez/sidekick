"""Tests for sidekick.timefmt (local-time rendering of event times)."""

from __future__ import annotations

from datetime import UTC, datetime

from sidekick import timefmt

LA = "America/Los_Angeles"


def test_to_local_converts_utc_and_offsets():
    assert timefmt.to_local("2026-11-20T02:40:00Z", LA).isoformat() == "2026-11-19T18:40:00-08:00"
    assert timefmt.to_local("2026-11-19T21:40:00-05:00", LA).hour == 18
    assert timefmt.to_local(datetime(2026, 11, 20, 2, 40, tzinfo=UTC), LA).hour == 18


def test_to_local_naive_means_local_and_dates_are_none():
    assert timefmt.to_local("2026-11-19T18:40:00", LA).isoformat() == "2026-11-19T18:40:00-08:00"
    assert timefmt.to_local("2026-11-19", LA) is None
    assert timefmt.to_local("not a dateTtime", LA) is None


def test_clock_has_no_leading_zero():
    assert timefmt.clock(datetime(2026, 1, 1, 6, 5)) == "6:05 AM"
    assert timefmt.clock(datetime(2026, 1, 1, 18, 40)) == "6:40 PM"


def test_format_event_span_same_day_next_day_and_all_day():
    assert (
        timefmt.format_event_span("2026-11-20T02:40:00Z", "2026-11-20T05:40:00Z", LA)
        == "Thu Nov 19, 6:40 PM - 9:40 PM"
    )
    assert (
        timefmt.format_event_span("2026-11-20T06:00:00Z", "2026-11-20T10:00:00Z", LA)
        == "Thu Nov 19, 10:00 PM - Fri Nov 20, 2:00 AM"
    )
    assert timefmt.format_event_span("2026-11-19", "2026-11-20", LA) == "Thu Nov 19 (all day)"
    assert (
        timefmt.format_event_span("2026-11-19T00:00:00Z", None, LA, all_day=True)
        == "Thu Nov 19 (all day)"
    )
    assert timefmt.format_event_span("garbage", None, LA) == "garbage"
