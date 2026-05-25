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
    """Local-tz day boundaries must be converted to ``Z``-suffix UTC.

    Chronary's ``GET /v1/agents/{id}/events`` rejects ISO 8601 forms with
    a numeric offset (``-07:00`` / ``+00:00``) and naive forms — only
    ``Z``-suffix UTC is accepted. So April 1 in LA (PDT, UTC-7) must map
    to ``2026-04-01T07:00:00Z`` .. ``2026-04-02T06:59:59Z``.
    """
    client = MagicMock()
    client.agents.events.list.return_value = []

    provider = _make_provider(client=client, timezone="America/Los_Angeles")
    provider.list_events({"start_date": "2026-04-01", "end_date": "2026-04-01"})

    kwargs = client.agents.events.list.call_args.kwargs
    assert kwargs["start_after"] == "2026-04-01T07:00:00Z"
    assert kwargs["start_before"] == "2026-04-02T06:59:59Z"


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


def test_list_events_unwraps_sync_pager():
    """Chronary SDK >=0.1.x returns a ``SyncPager`` whose entries live on ``.data``.

    The pager is not directly iterable, so the provider must unwrap it before
    mapping into plain dicts. Prior to this fix the ``/events`` page rendered a
    ``'SyncPager' object is not iterable`` error banner.
    """
    client = MagicMock()
    pager = SimpleNamespace(
        data=[
            SimpleNamespace(
                id="evt_2",
                title="Standup",
                start_time="2026-04-01T09:00:00-05:00",
                end_time="2026-04-01T09:15:00-05:00",
                description="",
                metadata=None,
            ),
        ],
    )
    client.agents.events.list.return_value = pager
    provider = _make_provider(client=client)

    result = provider.list_events({"start_date": "2026-04-01", "end_date": "2026-04-01"})

    assert len(result) == 1
    assert result[0]["id"] == "evt_2"
    assert result[0]["summary"] == "Standup"


# -------------------------------------------------------------------
# create_event
# -------------------------------------------------------------------


def test_create_event_passes_required_fields():
    """Datetimes with a numeric offset must be normalized to ``Z``-suffix UTC."""
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
    # 12:00 CDT (-05:00) == 17:00Z; 13:00 CDT == 18:00Z.
    assert kwargs["start_time"] == "2026-04-01T17:00:00Z"
    assert kwargs["end_time"] == "2026-04-01T18:00:00Z"
    assert "all_day" not in kwargs
    assert result["id"] == "evt_new"


def test_create_event_normalizes_naive_datetime_to_provider_tz():
    """The web dashboard's ``<input type="datetime-local">`` produces naive
    strings (``2026-04-01T12:00``). The provider must attach its configured
    timezone before converting to ``Z``-suffix UTC.
    """
    client = MagicMock()
    client.events.create.return_value = SimpleNamespace(id="evt_z", title="x")
    provider = _make_provider(client=client, timezone="America/Chicago")

    provider.create_event(
        {
            "summary": "x",
            "start_datetime": "2026-04-01T12:00",
            "end_datetime": "2026-04-01T13:00",
        }
    )

    kwargs = client.events.create.call_args.kwargs
    # April 1 in Chicago is CDT (UTC-5); 12:00 local == 17:00Z.
    assert kwargs["start_time"] == "2026-04-01T17:00:00Z"
    assert kwargs["end_time"] == "2026-04-01T18:00:00Z"


def test_create_event_passes_through_z_suffix_unchanged():
    """``Z``-suffix UTC input is already in the form Chronary wants."""
    client = MagicMock()
    client.events.create.return_value = SimpleNamespace(id="evt_z", title="x")
    provider = _make_provider(client=client)

    provider.create_event(
        {
            "summary": "x",
            "start_datetime": "2026-04-01T17:00:00Z",
            "end_datetime": "2026-04-01T18:00:00Z",
        }
    )

    kwargs = client.events.create.call_args.kwargs
    assert kwargs["start_time"] == "2026-04-01T17:00:00Z"
    assert kwargs["end_time"] == "2026-04-01T18:00:00Z"


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


def test_update_event_normalizes_datetimes_to_z():
    """``update_event`` shares ``create_event``'s Chronary constraint."""
    client = MagicMock()
    client.events.update.return_value = SimpleNamespace(
        id="evt_1",
        title="t",
        start_time="s",
        end_time="e",
        description="d",
        metadata={},
    )
    provider = _make_provider(client=client, timezone="America/Chicago")
    provider.update_event(
        {
            "event_id": "evt_1",
            "start_datetime": "2026-04-01T12:00",  # naive (dashboard form)
            "end_datetime": "2026-04-01T13:00:00-05:00",  # offset form (LLM)
        }
    )

    kwargs = client.events.update.call_args.kwargs
    assert kwargs["start_time"] == "2026-04-01T17:00:00Z"
    assert kwargs["end_time"] == "2026-04-01T18:00:00Z"


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
