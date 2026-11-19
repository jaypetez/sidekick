"""services.calendar.list_events uses the user's date, not the server's."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from sidekick.services import calendar as calendar_service


@pytest.mark.asyncio
async def test_list_events_window_starts_on_users_today(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "America/Los_Angeles")
    fixed = datetime(2026, 11, 20, 4, 0, tzinfo=ZoneInfo("UTC"))  # 8 PM PT, Nov 19

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(calendar_service, "datetime", _FixedDatetime)
    provider = MagicMock()
    provider.list_events.return_value = []

    await calendar_service.list_events(provider, days=7)

    args = provider.list_events.call_args.args[0]
    assert args["start_date"] == "2026-11-19"
    assert args["end_date"] == "2026-11-26"
