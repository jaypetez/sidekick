"""Verify opt-in bearer-token auth on the dashboard."""

from __future__ import annotations

import pytest
import pytest_asyncio

from sidekick.web import make_app


@pytest_asyncio.fixture
async def auth_client(aiohttp_client, bot_data, monkeypatch):
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", "s3cret-token")
    app = make_app(bot_data=bot_data)
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_dashboard_requires_token_when_configured(auth_client):
    resp = await auth_client.get("/")
    assert resp.status == 401
    assert "Bearer" in resp.headers.get("WWW-Authenticate", "")


@pytest.mark.asyncio
async def test_dashboard_accepts_valid_token(auth_client):
    resp = await auth_client.get("/", headers={"Authorization": "Bearer s3cret-token"})
    assert resp.status == 200


@pytest.mark.asyncio
async def test_dashboard_rejects_wrong_token(auth_client):
    resp = await auth_client.get("/", headers={"Authorization": "Bearer wrong"})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_health_returns_minimal_payload_without_token(auth_client):
    """Unauth probes get just the ok bit — no scheduler/MCP leak."""
    resp = await auth_client.get("/health")
    assert resp.status == 200
    payload = await resp.json()
    assert payload == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_returns_full_payload_with_token(auth_client):
    resp = await auth_client.get("/health", headers={"Authorization": "Bearer s3cret-token"})
    payload = await resp.json()
    assert "scheduler" in payload
    assert "mcp" in payload
    assert "tools" in payload


@pytest.mark.asyncio
async def test_static_assets_remain_public(auth_client):
    """We don't want CSS / favicon requests to 401 — they leak nothing."""
    resp = await auth_client.get("/static/style.css")
    # 200 if file exists, 404 if not — but never 401.
    assert resp.status != 401
