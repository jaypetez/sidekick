"""Tests for ChronaryProvider.

Uses a MagicMock chronary client — no real SDK calls.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sidekick.calendar.chronary import ChronaryProvider


@pytest.fixture
def chronary_env(monkeypatch):
    monkeypatch.setenv("CHRONARY_API_KEY", "chr_ak_test")
    monkeypatch.setenv("CHRONARY_AGENT_ID", "agt_test")
    monkeypatch.setenv("CHRONARY_CALENDAR_ID", "cal_test")


def _make_provider(client=None, timezone="America/Chicago"):
    return ChronaryProvider(
        client=client or MagicMock(),
        agent_id="agt_test",
        calendar_id="cal_test",
        timezone=timezone,
    )


# -------------------------------------------------------------------
# list_events
# -------------------------------------------------------------------


def test_list_events_uses_timezone_for_boundaries():
    """Timezone offset must apply to start_after / start_before."""
    client = MagicMock()
    client.agents.events.list.return_value = []

    provider = _make_provider(client=client, timezone="America/Los_Angeles")
    provider.list_events({"start_date": "2026-04-01", "end_date": "2026-04-01"})

    kwargs = client.agents.events.list.call_args.kwargs
    # April 1 in LA is in PDT — -07:00
    assert kwargs["start_after"] == "2026-04-01T00:00:00-07:00"
    assert kwargs["start_before"] == "2026-04-01T23:59:59-07:00"


def test_list_events_passes_agent_id_and_limit():
    client = MagicMock()
    client.agents.events.list.return_value = []

    provider = _make_provider(client=client)
    provider.list_events({"start_date": "2026-04-01", "end_date": "2026-04-02", "max_results": 50})

    args, kwargs = client.agents.events.list.call_args
    assert args[0] == "agt_test"
    assert kwargs["limit"] == 50


def test_list_events_maps_response_to_dicts():
    client = MagicMock()
    client.agents.events.list.return_value = [
        SimpleNamespace(
            id="evt_1",
            title="Team sync",
            start_time="2026-04-01T15:00:00-05:00",
            end_time="2026-04-01T16:00:00-05:00",
            description="Weekly",
            metadata={"location": "Room 4B"},
        ),
    ]
    provider = _make_provider(client=client)
    result = provider.list_events({"start_date": "2026-04-01", "end_date": "2026-04-01"})

    assert len(result) == 1
    e = result[0]
    assert e["id"] == "evt_1"
    assert e["summary"] == "Team sync"
    assert e["start"] == "2026-04-01T15:00:00-05:00"
    assert e["end"] == "2026-04-01T16:00:00-05:00"
    assert e["description"] == "Weekly"
    assert e["location"] == "Room 4B"


# -------------------------------------------------------------------
# create_event
# -------------------------------------------------------------------


def test_create_event_passes_required_fields():
    client = MagicMock()
    client.events.create.return_value = SimpleNamespace(
        id="evt_new", title="Lunch", url=None, html_link=None
    )
    provider = _make_provider(client=client)

    result = provider.create_event(
        {
            "summary": "Lunch",
            "start_datetime": "2026-04-01T12:00:00-05:00",
            "end_datetime": "2026-04-01T13:00:00-05:00",
        }
    )

    kwargs = client.events.create.call_args.kwargs
    assert kwargs["calendar_id"] == "cal_test"
    assert kwargs["title"] == "Lunch"
    assert kwargs["start_time"] == "2026-04-01T12:00:00-05:00"
    assert kwargs["end_time"] == "2026-04-01T13:00:00-05:00"
    assert "all_day" not in kwargs
    assert result["id"] == "evt_new"


def test_create_event_stashes_location_in_metadata():
    """Chronary has no `location` field — we use metadata."""
    client = MagicMock()
    client.events.create.return_value = SimpleNamespace(id="evt_x", title="X")
    provider = _make_provider(client=client)

    provider.create_event(
        {
            "summary": "Lunch",
            "start_datetime": "2026-04-01T12:00:00-05:00",
            "end_datetime": "2026-04-01T13:00:00-05:00",
            "location": "Cafe Bistro",
            "attendees": ["a@example.com", "b@example.com"],
        }
    )

    kwargs = client.events.create.call_args.kwargs
    assert kwargs["metadata"] == {
        "location": "Cafe Bistro",
        "attendees": ["a@example.com", "b@example.com"],
    }


def test_create_event_all_day_flag():
    """All-day events (no T in datetime) set all_day=True."""
    client = MagicMock()
    client.events.create.return_value = SimpleNamespace(id="evt_holiday", title="Holiday")
    provider = _make_provider(client=client)

    provider.create_event(
        {
            "summary": "Holiday",
            "start_datetime": "2026-12-25",
            "end_datetime": "2026-12-26",
        }
    )

    assert client.events.create.call_args.kwargs["all_day"] is True


# -------------------------------------------------------------------
# update_event
# -------------------------------------------------------------------


def test_update_event_partial_fields():
    client = MagicMock()
    client.events.update.return_value = SimpleNamespace(
        id="evt_1",
        title="New title",
        start_time="2026-04-01T15:00:00-05:00",
        end_time="2026-04-01T16:00:00-05:00",
        description="d",
        metadata={},
    )
    provider = _make_provider(client=client)
    provider.update_event({"event_id": "evt_1", "summary": "New title"})

    kwargs = client.events.update.call_args.kwargs
    assert kwargs["calendar_id"] == "cal_test"
    assert kwargs["event_id"] == "evt_1"
    assert kwargs["title"] == "New title"
    # Fields not provided are not in the patch
    assert "start_time" not in kwargs
    assert "metadata" not in kwargs


def test_update_event_with_location_merges_metadata():
    """Updating location must read existing metadata and merge."""
    client = MagicMock()
    client.events.get.return_value = SimpleNamespace(metadata={"attendees": ["a@x"]})
    client.events.update.return_value = SimpleNamespace(
        id="evt_1",
        title="t",
        start_time="s",
        end_time="e",
        description="d",
        metadata={},
    )
    provider = _make_provider(client=client)
    provider.update_event({"event_id": "evt_1", "location": "New Room"})

    kwargs = client.events.update.call_args.kwargs
    assert kwargs["metadata"] == {
        "attendees": ["a@x"],
        "location": "New Room",
    }


# -------------------------------------------------------------------
# delete_event
# -------------------------------------------------------------------


def test_delete_event_calls_sdk_and_returns_status():
    client = MagicMock()
    provider = _make_provider(client=client)
    result = provider.delete_event({"event_id": "evt_99"})

    client.events.delete.assert_called_once_with(calendar_id="cal_test", event_id="evt_99")
    assert result == {"status": "deleted", "event_id": "evt_99"}


# -------------------------------------------------------------------
# Env-based construction
# -------------------------------------------------------------------


def test_init_reads_ids_from_env(chronary_env):
    """Without explicit args, IDs come from env."""
    provider = ChronaryProvider(client=MagicMock())
    assert provider.agent_id == "agt_test"
    assert provider.calendar_id == "cal_test"
