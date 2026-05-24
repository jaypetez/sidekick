"""Verify security headers land on every dashboard response."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_security_headers_on_dashboard(client):
    resp = await client.get("/")
    assert resp.status == 200
    headers = resp.headers
    assert "Content-Security-Policy" in headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Permissions-Policy"] == "()"


@pytest.mark.asyncio
async def test_security_headers_on_health(client):
    """Headers must show up even on JSON endpoints (defense in depth)."""
    resp = await client.get("/health")
    assert resp.status == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert "Content-Security-Policy" in resp.headers
