"""Rate-limit behaviour for POST /chat."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from sidekick import ratelimit
from sidekick.web import make_app


@pytest.fixture(autouse=True)
def _tight_limit(monkeypatch):
    monkeypatch.setenv("SIDEKICK_RATE_LIMIT_MAX", "10")
    monkeypatch.setenv("SIDEKICK_RATE_LIMIT_WINDOW_SECONDS", "60")
    ratelimit.reset_default_limiter()
    yield
    ratelimit.reset_default_limiter()


@pytest.fixture
def chat_app(bot_data):
    bot_data["agent"].process_message = AsyncMock(return_value="ok")
    bot_data["agent"].conversation_history = {}
    bot_data["agent"].clear_history = MagicMock()
    return make_app(bot_data=bot_data)


@pytest_asyncio.fixture
async def chat_client(aiohttp_client, chat_app):
    from .conftest import CsrfClient

    return CsrfClient(await aiohttp_client(chat_app))


@pytest.mark.asyncio
async def test_eleventh_request_returns_429(chat_client):
    headers = {"X-Forwarded-For": "203.0.113.5"}
    # 10 requests should succeed (each returns 303 See Other since no HX-Request).
    for _ in range(10):
        resp = await chat_client.post(
            "/chat", data={"message": "hi"}, headers=headers, allow_redirects=False
        )
        assert resp.status in (200, 303)

    resp = await chat_client.post(
        "/chat", data={"message": "hi"}, headers=headers, allow_redirects=False
    )
    assert resp.status == 429
    body = await resp.json()
    assert body["error"] == "rate_limited"
    assert "too quickly" in body["message"].lower()


@pytest.mark.asyncio
async def test_different_xff_keys_are_isolated(chat_client, monkeypatch):
    # XFF is only trusted behind a declared reverse proxy.
    monkeypatch.setenv("SIDEKICK_WEB_TRUST_PROXY", "true")
    # First client uses up its budget.
    for _ in range(10):
        resp = await chat_client.post(
            "/chat",
            data={"message": "hi"},
            headers={"X-Forwarded-For": "1.1.1.1"},
            allow_redirects=False,
        )
        assert resp.status in (200, 303)

    resp = await chat_client.post(
        "/chat",
        data={"message": "hi"},
        headers={"X-Forwarded-For": "1.1.1.1"},
        allow_redirects=False,
    )
    assert resp.status == 429

    # A different XFF key still has its own bucket.
    resp = await chat_client.post(
        "/chat",
        data={"message": "hi"},
        headers={"X-Forwarded-For": "2.2.2.2"},
        allow_redirects=False,
    )
    assert resp.status in (200, 303)


@pytest.mark.asyncio
async def test_spoofed_xff_cannot_dodge_limit_by_default(chat_client, monkeypatch):
    """Without SIDEKICK_WEB_TRUST_PROXY, rotating X-Forwarded-For doesn't
    buy a fresh bucket — every request counts against the peer address."""
    monkeypatch.delenv("SIDEKICK_WEB_TRUST_PROXY", raising=False)
    statuses = []
    for i in range(11):
        resp = await chat_client.post(
            "/chat",
            data={"message": "hi"},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
            allow_redirects=False,
        )
        statuses.append(resp.status)
    assert statuses[-1] == 429
