"""Tests for the dashboard home page."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_dashboard_renders_with_healthy_state(client):
    resp = await client.get("/")
    assert resp.status == 200
    body = await resp.text()
    assert "Sidekick" in body
    assert "Running" in body  # scheduler tile
    assert "Up" in body  # MCP tile


@pytest.mark.asyncio
async def test_dashboard_shows_reminder_and_tool_counts(client, bot_data):
    bot_data["scheduler"].get_jobs.return_value = [object()] * 4
    bot_data["agent"].tools = [{"name": "n"} for _ in range(7)]
    resp = await client.get("/")
    body = await resp.text()
    assert ">4<" in body  # 4 reminders
    assert ">7<" in body  # 7 tools


@pytest.mark.asyncio
async def test_dashboard_shows_personality(client, bot_data):
    bot_data["agent"].personality = "Respond like a pirate."
    resp = await client.get("/")
    body = await resp.text()
    assert "Respond like a pirate." in body


@pytest.mark.asyncio
async def test_dashboard_falls_back_to_default_personality_label(client, bot_data):
    bot_data["agent"].personality = ""
    resp = await client.get("/")
    body = await resp.text()
    assert "default" in body.lower()
