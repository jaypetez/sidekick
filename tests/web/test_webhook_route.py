"""End-to-end tests for POST /webhooks/chronary through the full middleware stack."""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from sidekick.web import make_app
from sidekick.web.handlers.webhooks import WEBHOOK_TASKS_KEY
from sidekick.webhooks import WEBHOOK_PATH, DeliveryLog

from ..webhook_helpers import CALENDAR_ID, SECRET, reminder_payload, signed


@pytest.fixture
def webhook_env(monkeypatch):
    monkeypatch.setenv("CHRONARY_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("CHRONARY_CALENDAR_ID", CALENDAR_ID)
    monkeypatch.setenv("REMINDER_CHAT_ID", "-100123")
    monkeypatch.setenv("TIMEZONE", "UTC")


@pytest.fixture
def bot(bot_data):
    bot_data["agent"].bot.send_message = AsyncMock()
    return bot_data["agent"].bot


async def _make_client(aiohttp_client, bot_data):
    log = DeliveryLog(conn=sqlite3.connect(":memory:", check_same_thread=False))
    return await aiohttp_client(make_app(bot_data=bot_data, webhook_log=log))


@pytest_asyncio.fixture
async def hook_client(aiohttp_client, bot_data, webhook_env, bot):
    return await _make_client(aiohttp_client, bot_data)


async def _drain(client) -> None:
    tasks = list(client.server.app.get(WEBHOOK_TASKS_KEY) or ())
    if tasks:
        await asyncio.gather(*tasks)


async def _post(client, payload=None, **kw):
    body, headers = signed(payload or reminder_payload(), **kw)
    return await client.post(WEBHOOK_PATH, data=body, headers=headers)


@pytest.mark.asyncio
async def test_signed_reminder_is_delivered_to_telegram(hook_client, bot):
    resp = await _post(hook_client)
    assert resp.status == 200
    assert (await resp.json())["status"] == "accepted"
    await _drain(hook_client)
    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == -100123
    assert "Strategy sync" in kwargs["text"]


@pytest.mark.asyncio
async def test_duplicate_delivery_sends_once(hook_client, bot):
    """Chronary retries with the same X-Delivery-Id until it sees a 2xx."""
    first = await _post(hook_client, delivery_id="whd_same")
    second = await _post(hook_client, delivery_id="whd_same")
    await _drain(hook_client)
    assert first.status == second.status == 200
    assert (await second.json())["status"] == "duplicate"
    assert bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_unsigned_request_rejected(hook_client, bot):
    resp = await hook_client.post(WEBHOOK_PATH, json=reminder_payload())
    assert resp.status == 401
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_secret_rejected(hook_client, bot):
    resp = await _post(hook_client, secret="whsec_guess")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_other_calendar_ack_without_sending(hook_client, bot):
    resp = await _post(hook_client, reminder_payload(calendar_id="cal_other"))
    assert resp.status == 204
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_signed_garbage_is_400(hook_client):
    resp = await _post(hook_client, b'{"title": "no event id"}')
    assert resp.status == 400


@pytest.mark.asyncio
async def test_oversized_body_is_413(hook_client):
    body, headers = signed(b'{"pad": "' + b"x" * 70_000 + b'"}')
    resp = await hook_client.post(WEBHOOK_PATH, data=body, headers=headers)
    assert resp.status == 413


@pytest.mark.asyncio
async def test_route_absent_without_secret(aiohttp_client, bot_data, monkeypatch):
    monkeypatch.delenv("CHRONARY_WEBHOOK_SECRET", raising=False)
    client = await _make_client(aiohttp_client, bot_data)
    resp = await _post(client)
    assert resp.status == 404


@pytest.mark.asyncio
async def test_exempt_from_auth_csrf_and_host_check(
    aiohttp_client, bot_data, webhook_env, bot, monkeypatch
):
    """Chronary has no session, CSRF token or bearer, and a tunnel sends its
    public Host — the signature alone must be enough."""
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", "a-long-dashboard-token-123")
    client = await _make_client(aiohttp_client, bot_data)
    body, headers = signed(reminder_payload())
    headers["Host"] = "hooks.example.com"
    resp = await client.post(WEBHOOK_PATH, data=body, headers=headers)
    assert resp.status == 200

    # ...while the rest of the dashboard still demands auth.
    assert (await client.post("/chat/reset")).status in (401, 403)


@pytest.mark.asyncio
async def test_host_check_still_applies_elsewhere_with_auth_off(
    aiohttp_client, bot_data, webhook_env, bot, monkeypatch
):
    monkeypatch.delenv("SIDEKICK_WEB_AUTH_TOKEN", raising=False)
    client = await _make_client(aiohttp_client, bot_data)
    body, headers = signed(reminder_payload())
    headers["Host"] = "hooks.example.com"
    assert (await client.post(WEBHOOK_PATH, data=body, headers=headers)).status == 200
    assert (await client.get("/_csrf", headers={"Host": "hooks.example.com"})).status == 421


@pytest.mark.asyncio
async def test_exemption_is_exact_path(hook_client):
    body, headers = signed(reminder_payload())
    resp = await hook_client.post(WEBHOOK_PATH + "x", data=body, headers=headers)
    assert resp.status in (403, 404)  # CSRF still applies; no such route


@pytest.mark.asyncio
async def test_web_only_mode_acks_without_bot(aiohttp_client, bot_data, webhook_env):
    bot_data["agent"].bot = None
    client = await _make_client(aiohttp_client, bot_data)
    resp = await _post(client)
    await _drain(client)
    assert resp.status == 200


@pytest.mark.asyncio
async def test_health_reports_last_delivery(hook_client):
    before = await (await hook_client.get("/api/health")).json()
    assert before["data"]["webhook"]["configured"] is True
    assert before["data"]["webhook"]["last_received_at"] is None
    await _post(hook_client)
    after = await (await hook_client.get("/api/health")).json()
    assert after["data"]["webhook"]["last_received_at"] is not None


@pytest.mark.asyncio
async def test_secret_file_fallback(aiohttp_client, bot_data, bot, monkeypatch, tmp_path):
    """sidekick-webhook register stores the secret in a 0600 file; the route
    must accept deliveries with only that file configured."""
    monkeypatch.delenv("CHRONARY_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONARY_CALENDAR_ID", CALENDAR_ID)
    monkeypatch.setenv("REMINDER_CHAT_ID", "-100123")
    (tmp_path / "chronary_webhook.secret").write_text(SECRET + "\n")
    client = await _make_client(aiohttp_client, bot_data)
    resp = await _post(client)
    await _drain(client)
    assert resp.status == 200
    bot.send_message.assert_awaited_once()
