"""Verify CSRF protection on every state-changing route.

The ``raw_client`` fixture (defined in conftest.py) deliberately does
NOT auto-inject CSRF tokens so these tests can exercise both the
missing-token path (403) and the valid-token path (200/302/303).

All comparisons rely on :func:`hmac.compare_digest` semantics — see
``sidekick.web.csrf.validate_token``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# Routes that must reject POSTs without a valid CSRF token.
PROTECTED_POSTS = [
    ("/chat", {"message": "hi"}),
    ("/chat/reset", {}),
    ("/settings/personality", {"style": "pirate"}),
    ("/reminders", {"message": "x", "hour": "9", "minute": "0"}),
    ("/reminders/morning_summary", {"enabled": "false"}),
    ("/reminders/x/delete", {}),
    ("/tasks/Costco/items", {"title": "milk"}),
    ("/tasks/Costco/items/1/complete", {}),
    ("/tasks/Costco/items/1/delete", {}),
    ("/tasks/Costco/clear-completed", {}),
    ("/tasks/Costco/delete", {}),
    ("/events", {"summary": "x", "start_datetime": "y", "end_datetime": "z"}),
    ("/events/abc", {"summary": "x"}),
    ("/events/abc/delete", {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", PROTECTED_POSTS)
async def test_post_without_csrf_is_forbidden(raw_client, path, payload):
    """Every state-changing route returns 403 when the token is missing."""
    resp = await raw_client.post(path, data=payload, allow_redirects=False)
    assert resp.status == 403, f"{path} should require CSRF token"


@pytest.mark.asyncio
async def test_post_with_wrong_csrf_is_forbidden(raw_client, bot_data):
    """A token-shaped string that doesn't match the session token is rejected."""
    bot_data["agent"].process_message = AsyncMock(return_value="ok")
    # Fetch a valid token to establish a session, then submit a different value.
    await raw_client.get("/_csrf")
    resp = await raw_client.post(
        "/chat", data={"message": "hi", "_csrf": "not-the-real-token"}, allow_redirects=False
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_post_with_valid_csrf_succeeds(raw_client, bot_data):
    """When the form echoes the right token, the request goes through."""
    bot_data["agent"].process_message = AsyncMock(return_value="ok")
    token_resp = await raw_client.get("/_csrf")
    token = (await token_resp.json())["csrf"]
    resp = await raw_client.post(
        "/chat", data={"message": "hi", "_csrf": token}, allow_redirects=False
    )
    assert resp.status == 303


@pytest.mark.asyncio
async def test_post_with_csrf_header_succeeds(raw_client, bot_data):
    """htmx submits the token via X-CSRF-Token; that path must also work."""
    bot_data["agent"].process_message = AsyncMock(return_value="ok")
    token_resp = await raw_client.get("/_csrf")
    token = (await token_resp.json())["csrf"]
    resp = await raw_client.post(
        "/chat",
        data={"message": "hi"},
        headers={"X-CSRF-Token": token, "HX-Request": "true"},
        allow_redirects=False,
    )
    assert resp.status == 200


@pytest.mark.asyncio
async def test_get_does_not_require_csrf(raw_client):
    """GETs are read-only; the middleware leaves them alone."""
    resp = await raw_client.get("/health")
    assert resp.status == 200
