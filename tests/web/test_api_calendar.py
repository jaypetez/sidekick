"""Tests for /api/events endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from sidekick.web import make_app

from .conftest import CsrfClient


@pytest.fixture
def calendar_provider():
    provider = MagicMock()
    provider.list_events.return_value = [
        {"id": "evt_1", "summary": "Dentist", "start": "2026-05-24T09:00:00-05:00"}
    ]
    provider.create_event.return_value = {"id": "evt_new", "summary": "Standup"}
    provider.update_event.return_value = {"id": "evt_1", "summary": "Updated"}
    provider.delete_event.return_value = {"status": "deleted", "event_id": "evt_1"}
    return provider


@pytest_asyncio.fixture
async def cal_client(aiohttp_client, bot_data, calendar_provider):
    inner = await aiohttp_client(make_app(bot_data=bot_data, calendar_provider=calendar_provider))
    return CsrfClient(inner)


@pytest.mark.asyncio
async def test_list_events_returns_envelope(cal_client):
    resp = await cal_client.get("/api/events")
    assert resp.status == 200
    payload = await resp.json()
    assert payload["data"]["events"][0]["summary"] == "Dentist"
    assert payload["data"]["days"] == 14


@pytest.mark.asyncio
async def test_list_events_respects_days(cal_client, calendar_provider):
    await cal_client.get("/api/events?days=7")
    args = calendar_provider.list_events.call_args.args[0]
    # 7-day window — end - start should be 7 days
    from datetime import date

    start = date.fromisoformat(args["start_date"])
    end = date.fromisoformat(args["end_date"])
    assert (end - start).days == 7


@pytest.mark.asyncio
async def test_create_event_validates_required(cal_client):
    resp = await cal_client.post("/api/events", json={"summary": "only summary"})
    assert resp.status == 400
    payload = await resp.json()
    assert payload["error"]["code"] == "missing_field"


@pytest.mark.asyncio
async def test_create_event_happy_path(cal_client, calendar_provider):
    resp = await cal_client.post(
        "/api/events",
        json={
            "summary": "Standup",
            "start_datetime": "2026-05-24T09:00",
            "end_datetime": "2026-05-24T09:30",
        },
    )
    assert resp.status == 201
    payload = await resp.json()
    assert payload["data"]["id"] == "evt_new"


@pytest.mark.asyncio
async def test_update_event_requires_at_least_one_field(cal_client):
    resp = await cal_client.patch("/api/events/evt_1", json={})
    assert resp.status == 400
    payload = await resp.json()
    assert payload["error"]["code"] == "missing_field"


@pytest.mark.asyncio
async def test_delete_event(cal_client, calendar_provider):
    resp = await cal_client.delete("/api/events/evt_1")
    assert resp.status == 200
    calendar_provider.delete_event.assert_called_once_with({"event_id": "evt_1"})
