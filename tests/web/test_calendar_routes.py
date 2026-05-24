"""Tests for /events routes (calendar CRUD)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from sidekick.web import make_app


@pytest.fixture
def calendar_provider():
    provider = MagicMock()
    provider.list_events.return_value = [
        {
            "id": "evt_1",
            "summary": "Dentist",
            "start": "2026-05-24T09:00:00-05:00",
            "end": "2026-05-24T10:00:00-05:00",
            "location": "Downtown",
            "description": "",
            "attendees": [],
        }
    ]
    provider.create_event.return_value = {
        "id": "evt_new",
        "summary": "Standup",
        "htmlLink": None,
    }
    provider.update_event.return_value = {"id": "evt_1", "summary": "Updated"}
    provider.delete_event.return_value = {"status": "deleted", "event_id": "evt_1"}
    return provider


@pytest.fixture
def cal_app(bot_data, calendar_provider):
    return make_app(bot_data=bot_data, calendar_provider=calendar_provider)


@pytest_asyncio.fixture
async def cal_client(aiohttp_client, cal_app):
    return await aiohttp_client(cal_app)


@pytest.mark.asyncio
async def test_index_lists_upcoming_events(cal_client, calendar_provider):
    resp = await cal_client.get("/events")
    assert resp.status == 200
    body = await resp.text()
    assert "Dentist" in body
    calendar_provider.list_events.assert_called_once()
    args = calendar_provider.list_events.call_args.args[0]
    assert "start_date" in args and "end_date" in args


@pytest.mark.asyncio
async def test_index_respects_days_query(cal_client, calendar_provider):
    await cal_client.get("/events?days=7")
    args = calendar_provider.list_events.call_args.args[0]
    # 7 days inclusive => the date math is start..start+7
    assert args["start_date"] != args["end_date"]


@pytest.mark.asyncio
async def test_index_clamps_invalid_days_to_default(cal_client, calendar_provider):
    """Non-integer ``days`` falls back to 14 instead of 500'ing."""
    resp = await cal_client.get("/events?days=abc")
    assert resp.status == 200


@pytest.mark.asyncio
async def test_create_posts_required_fields(cal_client, calendar_provider):
    resp = await cal_client.post(
        "/events",
        data={
            "summary": "Standup",
            "start_datetime": "2026-05-25T09:00:00-05:00",
            "end_datetime": "2026-05-25T09:15:00-05:00",
            "location": "Zoom",
        },
        allow_redirects=False,
    )
    assert resp.status == 303
    assert resp.headers["Location"] == "/events"
    args = calendar_provider.create_event.call_args.args[0]
    assert args["summary"] == "Standup"
    assert args["location"] == "Zoom"


@pytest.mark.asyncio
async def test_create_rejects_missing_required(cal_client, calendar_provider):
    resp = await cal_client.post(
        "/events",
        data={"summary": ""},
        allow_redirects=False,
    )
    assert resp.status == 400
    calendar_provider.create_event.assert_not_called()


@pytest.mark.asyncio
async def test_update_passes_only_provided_fields(cal_client, calendar_provider):
    resp = await cal_client.post(
        "/events/evt_1",
        data={"summary": "New name"},
        allow_redirects=False,
    )
    assert resp.status == 303
    args = calendar_provider.update_event.call_args.args[0]
    assert args["event_id"] == "evt_1"
    assert args["summary"] == "New name"
    assert "description" not in args


@pytest.mark.asyncio
async def test_update_rejects_when_no_fields_provided(cal_client, calendar_provider):
    resp = await cal_client.post(
        "/events/evt_1",
        data={},
        allow_redirects=False,
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_delete_calls_provider(cal_client, calendar_provider):
    resp = await cal_client.post("/events/evt_1/delete", allow_redirects=False)
    assert resp.status == 303
    calendar_provider.delete_event.assert_called_once_with({"event_id": "evt_1"})


@pytest.mark.asyncio
async def test_index_503s_without_provider(aiohttp_client, bot_data):
    """When no calendar provider is wired (e.g. CHRONARY_* missing), 503."""
    app = make_app(bot_data=bot_data)
    c = await aiohttp_client(app)
    resp = await c.get("/events")
    assert resp.status == 503


@pytest.mark.asyncio
async def test_index_renders_error_banner_when_provider_fails(cal_client, calendar_provider):
    """A live but-erroring provider shouldn't 500 — show the user what went wrong."""
    calendar_provider.list_events.side_effect = RuntimeError("Chronary 401")
    resp = await cal_client.get("/events")
    assert resp.status == 200
    body = await resp.text()
    assert "Chronary 401" in body
    # Body should still render the page chrome (no traceback page).
    assert "Calendar" in body


@pytest.mark.asyncio
async def test_create_502s_when_provider_fails(cal_client, calendar_provider):
    calendar_provider.create_event.side_effect = RuntimeError("Chronary 500")
    resp = await cal_client.post(
        "/events",
        data={
            "summary": "x",
            "start_datetime": "2026-05-25T09:00:00-05:00",
            "end_datetime": "2026-05-25T09:30:00-05:00",
        },
        allow_redirects=False,
    )
    assert resp.status == 502


@pytest.mark.asyncio
async def test_delete_502s_when_provider_fails(cal_client, calendar_provider):
    calendar_provider.delete_event.side_effect = RuntimeError("nope")
    resp = await cal_client.post("/events/evt_1/delete", allow_redirects=False)
    assert resp.status == 502
