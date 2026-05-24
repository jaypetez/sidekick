"""Fixtures for web dashboard tests.

Mirrors the mocking style of ``tests/conftest.py`` — handlers see a
fully mocked ``bot_data`` dict, never a real scheduler / agent / MCP
session. Tests against rendered HTML use the ``aiohttp_client`` fixture
from pytest-aiohttp.

CSRF auto-injection
-------------------

PR #1 of the security tier enables CSRF on every state-changing route.
The handful of pre-existing tests POST without ever fetching a token,
so the ``client`` / ``tasks_client`` / ``chat_client`` fixtures wrap
the ``TestClient`` with :class:`CsrfClient` which transparently fetches
``/_csrf`` once and injects ``_csrf`` into form bodies + the
``X-CSRF-Token`` header. Tests that *want* to assert CSRF behaviour
(see ``test_csrf.py``) use the raw ``aiohttp_client`` fixture directly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from sidekick.web import make_app


class CsrfClient:
    """Thin wrapper around aiohttp's TestClient that auto-injects CSRF.

    Delegates everything except ``post`` to the underlying client. ``post``
    is wrapped to (a) lazily fetch a CSRF token on the first call and
    (b) merge it into the form body and ``X-CSRF-Token`` header. Cookies
    set on the GET propagate to the POST via the shared TestClient
    cookie jar.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._token: str | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def _ensure_token(self) -> str:
        if self._token is None:
            resp = await self._inner.get("/_csrf")
            data = await resp.json()
            self._token = str(data["csrf"])
        return self._token

    async def post(self, path: str, **kwargs: Any) -> Any:
        token = await self._ensure_token()
        data = kwargs.get("data")
        if isinstance(data, dict):
            kwargs["data"] = {**data, "_csrf": token}
        else:
            # FormData / bytes / None — fall back to header-only.
            pass
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("X-CSRF-Token", token)
        kwargs["headers"] = headers
        return await self._inner.post(path, **kwargs)


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
    raw = await aiohttp_client(app)
    return CsrfClient(raw)


@pytest_asyncio.fixture
async def raw_client(aiohttp_client, app):
    """A client that does NOT auto-inject CSRF — used by test_csrf.py."""
    return await aiohttp_client(app)
