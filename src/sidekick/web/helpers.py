"""Helpers shared across web handlers.

``run_sync`` was promoted to :mod:`sidekick.util` so the new services
layer can use it without taking a dependency on the web package. This
module re-exports it so existing handler imports keep working.
"""

from __future__ import annotations

import os

from aiohttp import web

from ..util import run_sync

__all__ = ["client_ip", "run_sync"]


def _trust_proxy() -> bool:
    return os.getenv("SIDEKICK_WEB_TRUST_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}


def client_ip(request: web.Request) -> str:
    """Best-effort client address for rate limiting and logging.

    ``X-Forwarded-For`` is client-controlled, so it is only honored when
    ``SIDEKICK_WEB_TRUST_PROXY`` says a reverse proxy in front of us sets it.
    Otherwise a caller could rotate the header to dodge every rate limit.
    """
    if _trust_proxy():
        xff = request.headers.get("X-Forwarded-For", "")
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.remote or "unknown"
