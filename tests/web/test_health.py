"""Tests for the /health JSON endpoint."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_reports_healthy_state(client, bot_data):
    resp = await client.get("/health")
    assert resp.status == 200
    payload = await resp.json()
    assert payload == {"scheduler": True, "mcp": True, "reminders": 0, "tools": 2}


@pytest.mark.asyncio
async def test_health_reports_scheduler_down(client, bot_data):
    bot_data["scheduler"].running = False
    resp = await client.get("/health")
    payload = await resp.json()
    assert payload["scheduler"] is False


@pytest.mark.asyncio
async def test_health_reports_mcp_down(client, bot_data):
    bot_data["mcp_task"].done.return_value = True
    resp = await client.get("/health")
    payload = await resp.json()
    assert payload["mcp"] is False


@pytest.mark.asyncio
async def test_health_counts_active_reminders(client, bot_data):
    bot_data["scheduler"].get_jobs.return_value = [object(), object(), object()]
    resp = await client.get("/health")
    payload = await resp.json()
    assert payload["reminders"] == 3


@pytest.mark.asyncio
async def test_health_tolerates_missing_state(aiohttp_client):
    """When bot_data is empty (startup race), health degrades gracefully."""
    from sidekick.web import make_app

    app = make_app(bot_data={})
    c = await aiohttp_client(app)
    resp = await c.get("/health")
    assert resp.status == 200
    payload = await resp.json()
    assert payload == {"scheduler": False, "mcp": False, "reminders": 0, "tools": 0}
