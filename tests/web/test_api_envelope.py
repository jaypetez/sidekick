"""Tests for the /api/* envelope shape + error middleware."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_returns_envelope(client):
    resp = await client.get("/api/health")
    assert resp.status == 200
    payload = await resp.json()
    assert set(payload.keys()) == {"data", "error"}
    assert payload["error"] is None
    assert isinstance(payload["data"], dict)
    assert "scheduler" in payload["data"]


@pytest.mark.asyncio
async def test_unknown_api_route_returns_envelope_404(client):
    resp = await client.get("/api/no-such-thing")
    assert resp.status == 404
    payload = await resp.json()
    assert payload["data"] is None
    assert payload["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_invalid_json_body_returns_envelope_400(client, bot_data):
    resp = await client.post(
        "/api/chat", data="{not json", headers={"Content-Type": "application/json"}
    )
    assert resp.status == 400
    payload = await resp.json()
    assert payload["error"]["code"] == "invalid_json"


@pytest.mark.asyncio
async def test_service_unavailable_wrapped_as_envelope(aiohttp_client):
    """Endpoints that need agent/store/calendar surface 503 via the envelope."""
    from sidekick.web import make_app

    app = make_app(bot_data={})
    c = await aiohttp_client(app)
    resp = await c.get("/api/reminders")
    assert resp.status == 503
    payload = await resp.json()
    assert payload["error"]["code"] == "service_unavailable"


@pytest.mark.asyncio
async def test_unhandled_error_does_not_leak_exception_text(aiohttp_client, bot_data):
    from unittest.mock import MagicMock

    from sidekick.web import make_app

    store = MagicMock()
    store.list_task_lists.side_effect = RuntimeError("/home/app/.config/sidekick/secret.db")
    c = await aiohttp_client(make_app(bot_data=bot_data, task_store=store))
    resp = await c.get("/api/tasks")
    assert resp.status == 500
    payload = await resp.json()
    assert payload["error"]["code"] == "internal_error"
    assert "secret.db" not in payload["error"]["message"]
