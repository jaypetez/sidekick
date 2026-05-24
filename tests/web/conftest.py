"""Fixtures for web dashboard tests.

Mirrors the mocking style of ``tests/conftest.py`` — handlers see a
fully mocked ``bot_data`` dict, never a real scheduler / agent / MCP
session. Tests against rendered HTML use the ``aiohttp_client`` fixture
from pytest-aiohttp.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from sidekick.web import make_app


@pytest.fixture
def bot_data() -> dict[str, Any]:
    """Mock the live bot_data dict the web handlers read from."""
    scheduler = MagicMock()
    scheduler.running = True
    scheduler.get_jobs.return_value = []

    agent = MagicMock()
    agent.tools = [{"name": "list_events"}, {"name": "add_tasks"}]
    agent.personality = ""

    mcp_task = MagicMock()
    mcp_task.done.return_value = False

    return {
        "scheduler": scheduler,
        "agent": agent,
        "mcp_task": mcp_task,
    }


@pytest.fixture
def app(bot_data):
    return make_app(bot_data=bot_data)


@pytest_asyncio.fixture
async def client(aiohttp_client, app):
    return await aiohttp_client(app)
