"""Shared CLI test helpers.

The CLI talks HTTP via httpx; we mount an in-memory transport that
returns canned envelope-shaped responses. No real network, no
running sidekick server.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from sidekick.cli.client import ApiClient


@pytest.fixture
def make_client() -> Callable[..., ApiClient]:
    """Return a factory that builds an ApiClient backed by a MockTransport.

    Usage:

        def test_x(make_client):
            requests = []
            def handler(request):
                requests.append(request)
                return httpx.Response(200, json={"data": {"ok": True}, "error": None})
            client = make_client(handler)
            ...
    """

    def _factory(handler: Callable[[httpx.Request], httpx.Response]) -> ApiClient:
        transport = httpx.MockTransport(handler)
        c = ApiClient(base_url="http://test")
        # Replace the live httpx.Client with one bound to the mock transport.
        c._client.close()
        c._client = httpx.Client(base_url="http://test", transport=transport)
        return c

    return _factory


def envelope_ok(data: Any) -> dict[str, Any]:
    return {"data": data, "error": None}


def envelope_err(code: str, message: str) -> dict[str, Any]:
    return {"data": None, "error": {"code": code, "message": message}}


def parse_body(request: httpx.Request) -> Any:
    if not request.content:
        return None
    return json.loads(request.content)
